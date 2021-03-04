#!/usr/bin/env python3

import sys
from lxml import html
import requests
from getpass import getpass, getuser
import curses
from curses.textpad import Textbox, rectangle
import time
import pickle
import json
import os

class Session:
    def __init__(self, email=None, password=None):
        # Start a session
        self.session = requests.session()

        # Get an authenticity token... I'm totally not a robot
        login = html.fromstring(self.session.get('https://gradescope.com/login').content)
        token = login.xpath('//form//input[@name="authenticity_token"]')[0].get('value')

        # Get the authentication information if not provided
        if email == None:
            email = input("Enter your email: ")

        if password == None:
            password = getpass(prompt="Enter your password: ")

        # Login
        data = {
            'utf8': '✓',
            'authenticity_token': token,
            'session[email]': email,
            'session[password]': password,
            'session[remember_me]': '0',
            'commit': 'Log In',
            'session[remember_me_sso]': '0',
        }
        headers = {
            'Host': 'www.gradescope.com',
            'Referer': 'https://www.gradescope.com',
        }
        if b"<title>Dashboard | Gradescope</title>" not in self.session.post("https://gradescope.com/login", data=data, headers=headers).content:
            print("Could not login with provided credentials.")
            sys.exit(1)

    def load_submissions(self, course_id, question_id, start, limit=None):
        details = html.fromstring(self.session.get("https://www.gradescope.com/courses/{}/questions/{}/submissions".format(course_id, question_id)).content)
        rows = details.xpath('//*[@id="question_submissions"]//td[contains(concat(" ",normalize-space(@class)," "),"table--primaryLink")]//a')[start:]
        if not limit == None:
            rows = rows[0:limit]
        subs = {}
        i = 0
        print("\rLoading questions [{} of {}]".format(i, len(rows)), end='')
        for row in rows:
            submission_id = int(row.attrib['href'].split('/')[6])
            resp = self.session.get("https://www.gradescope.com/courses/{}/questions/{}/submissions/{}/grade".format(course_id, question_id, submission_id))
            submission_content = html.fromstring(resp.content)
            session = ""
            for cookie in resp.headers["Set-Cookie"].split("; "):
                if cookie[:19] == "_gradescope_session":
                    session = cookie[20:]
            subs[submission_id] = {
                "content": json.loads(submission_content.xpath('//div[@data-react-class="SubmissionGrader"]')[0].attrib["data-react-props"]),
                "auth": {
                    "token": submission_content.xpath('//meta[@name="csrf-token"]')[0].attrib["content"],
                    "session": session
                }
            }
            i += 1
            print("\rLoading questions [{} of {}]".format(i, len(rows)), end='')
        print("\rLoading questions [done]         ")
        return subs

#    def grade(self, course_id, question_id, submission_id, data, auth):
#        headers = {
#            'Host': 'www.gradescope.com',
#            'Referer': 'https://www.gradescope.com/courses/{}/questions/{}/submissions/{}/grade'.format(course_id, question_id, submission_id),
#            'Origin': 'https://www.gradescope.com',
#            'X-CSRF-Token': auth["token"],
#            'X-Requested-With': 'XMLHttpRequest',
#            'Accept': 'application/json, text/javascript, */*; q=0.01',
#        }
#        result = self.session.post("https://www.gradescope.com/courses/{}/questions/{}/submissions/{}/save_grade".format(course_id, question_id, submission_id), json=data, headers=headers)
#        return json.loads(result.content)

class Grouping:
    def __init__(self):
        # Get credentials
        if len(sys.argv) < 4:
            print("Usage: {} <email> <password> <courseid> <questionid> <parts>".format(sys.argv[0]))
            sys.exit(1)

        email = sys.argv[1]
        password = sys.argv[2]

        if input("WARNING: this may overwrite grading progress.  Proceed? [y/N] ").lower() not in ["y", "yes"]:
            print("Aborting")
            sys.exit(1)

        # Login to Gradescope
        self.session = Session(email, password)

        # Get submissions
        self.submissions = self.session.load_submissions(int(sys.argv[3]), int(sys.argv[4]), 0, 20)

        # Convert submissions to just their contents
        self.answers = {}
        for sid in self.submissions:
            t = self.submissions[sid]["content"]["submission"]["answers"]
            t1 = {}
            mx = 0
            for k in t:
                t1[int(k)] = t[k]
                mx = max(mx, int(k))
            self.answers[sid] = []
            for i in range(mx + 1):
                if i in t1:
                    self.answers[sid].append(t1[i])
                else:
                    self.answers[sid].append("")

        # Get specified parts
        self.parts = list(map(lambda x: int(x.strip()), sys.argv[5].split(",")))

        # Remap IDs
        self.ids = list(self.submissions.keys())
        self.answers2 = []
        for i in range(len(self.ids)):
            sid = list(self.ids)[i]
            self.answers2.append(self.answers[sid])
        self.answers = self.answers2

        # Get longest length of each part
        self.longest = [0 for _ in self.answers[0]]
        for a in self.answers:
            for p in range(len(a)):
                self.longest[p] = max(self.longest[p], len(a[p]))

    def form_groups(self):
        try:
            # Start curses
            stdscr = curses.initscr()
            curses.noecho()
            curses.cbreak()
            stdscr.keypad(True)
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_RED, -1)#curses.COLOR_BLACK)
            curses.init_pair(2, 14, -1)#curses.COLOR_BLACK)
            curses.init_pair(3, curses.COLOR_GREEN, -1)#curses.COLOR_BLACK)

            groups = {}
            ungrouped = list(range(len(self.answers)))

            # Begin loop
            text = ""
            g_tmp = {}
            g_off = 0
            while True:
                valid = False
                if "quit".startswith(text) or "exit".startswith(text):
                    valid = True
                g_tmp = self.validate_command(text, groups, ungrouped)
                if g_tmp != False:
                    valid = True
                else:
                    g_tmp = {}
                y, x = self.draw_screen(stdscr, groups, ungrouped, text, valid, g_tmp, g_off)

                # Get input
                c = stdscr.getch(y, x)
                if ord(' ') <= c <= ord('~'):
                    text += chr(c)
                elif c in [8, 127, curses.KEY_BACKSPACE] and len(text) > 0:
                    text = text[:-1]
                elif c in [10, 13, curses.KEY_ENTER]:
                    if "quit".startswith(text) or "exit".startswith(text):
                        break
                    if self.process_command(text, groups, ungrouped):
                        g_tmp = {}
                        text = ""
                elif c == 260:
                    # left
                    if g_off > 0:
                        g_off -= 1
                elif c == 261:
                    # right
                    if g_off < len(groups) - 1:
                        g_off += 1

        finally:
            # save groups
            filename = self.save_groups(groups, ungrouped)

            # Terminate curses
            curses.nocbreak()
            stdscr.keypad(False)
            curses.echo()
            curses.endwin()

            print(f"Session saved in {filename}")

    def draw_screen(self, stdscr, groups, ungrouped, cmd, valid, g_tmp, g_off):
        stdscr.erase()
        # Get screen size
        height, width = stdscr.getmaxyx()

        group_width = min(height, 48)
        group_height = min(width, 12)

        # Draw the ungrouped answers as a list
        for i in range(height - group_height - 5):
            if i >= len(ungrouped):
                break
            # temp group
            for g in g_tmp:
                if ungrouped[i] in g_tmp[g]:
                    stdscr.addstr(i, 0, g, curses.color_pair(3))

            # number
            if i % 2 == 1:
                stdscr.addstr(i, 4, f"{ungrouped[i]}.", curses.color_pair(2))
            else:
                stdscr.addstr(i, 4, f"{ungrouped[i]}.")

            # answers
            x = 9
            for p in range(len(self.parts)):
                if i % 2 == 1:
                    stdscr.addstr(i, x, self.answers[ungrouped[i]][self.parts[p]], curses.color_pair(2))
                else:
                    stdscr.addstr(i, x, self.answers[ungrouped[i]][self.parts[p]])
                x += self.longest[self.parts[p]] + 5

        # Draw the groups along the bottom, one row, with most recent additions shown
        x = 0
        for g in list(groups.keys())[g_off:]:
            if x + group_width - 1 >= width:
                break
            rectangle(stdscr, height - group_height, x, height - 1, x + group_width - 1)
            stdscr.addstr(height - group_height, x + 3, f" {g} ")

            i = 0
            for sub in groups[g]["submissions"][::-1][:(group_height-1)]:
                stdscr.addstr(height - group_height + i + 1, x + 1, str(self.get_submission(sub))[:(group_width - 2)])
                i += 1

            x += group_width


        # Draw the input box
        rectangle(stdscr, height - group_height - 4, 0, height - group_height - 2, width - 1)
        ell = False
        while len(cmd) > width - 5:
            cmd = cmd[1:]
            ell = True
        if ell:
            cmd = "..." + cmd[3:]

        if not valid:
            stdscr.addstr(height - group_height - 3, 2, cmd, curses.color_pair(1))
        else:
            stdscr.addstr(height - group_height - 3, 2, cmd)
        stdscr.refresh()

        return height - group_height - 3, len(cmd) + 2

    def get_submission(self, num):
        s = []
        for p in self.parts:
            s.append(self.answers[num][p])
        return s

    def get_submission_id(self, num):
        return self.ids[num]

    def validate_command(self, cmd, saved_groups, ungrouped):
        groups = {}

        try:
            parts = cmd.split(" ")
            for p in parts:
                if "/" in p:
                    g, subs = p.split("/")
                else:
                    g, subs = p, ""
                # make sure group name is all uppercase
                for c in g:
                    if not ord("A") <= ord(c) <= ord("Z"):
                        return False
                groups[g] = []
                if subs != "":
                    try:
                        subs = list(map(int, filter(lambda x: x != "", subs.split(","))))
                    except:
                        return False
                    # make sure all subs exist
                    for s in subs:
                        if s not in ungrouped:
                            return False
                        groups[g].append(s)
            # ensure no dups
            for g in groups:
                for h in groups:
                    if g != h:
                        for s in groups[g]:
                            if s in groups[h]:
                                return False

        except:
            return False

        # add identical answers to same group
        for g in groups:
            to_add = []
            for s in groups[g]:
                for n in ungrouped:
                    if n != s and self.get_submission(s) == self.get_submission(n):
                        to_add.append(n)
            groups[g] += to_add
        
        return groups

    def process_command(self, cmd, groups, ungrouped):
        new_grouping = self.validate_command(cmd, groups, ungrouped)
        if new_grouping == False:
            return False

        # Apply the groups
        for group in new_grouping:
            if group not in groups:
                groups[group] = {
                    "submissions": [],
                    "rubric": []
                }

            for sub in new_grouping[group]:
                groups[group]["submissions"].append(sub)
                ungrouped.remove(sub)

        return True

    def save_groups(self, groups, ungrouped):
        data = {
            "groups": {},
            "ungrouped": []
        }

        for g in groups:
            data["groups"][g] = {
                "submission_ids": [],
                "rubric": groups[g]["rubric"],
            }
            for s in groups[g]["submissions"]:
                data["groups"][g]["submission_ids"].append(self.get_submission_id(s))
        for s in ungrouped:
            data["ungrouped"].append(self.get_submission_id(s))

        i = 0
        while True:
            filename = f"session-{i}.bin"
            if not os.path.exists(filename):
                break
            i += 1
        
        pickle.dump(data, open(filename, "wb"))

        return filename

if __name__ == '__main__':
    g = Grouping()
    g.form_groups()

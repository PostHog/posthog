#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""Sort hoglint's new rows by the lines a change touches, while hoglint runs in shadow.

In shadow CI does not block, so master can carry findings that the ledger does not record yet,
and every later check reports them. A row belongs to a change only when its place is a line the
change adds or edits, so the script reads the change's diff at zero context. It reads hoglint's
full view (`--all`) from stdout alone, because the default view can cut the list short and
stderr can hold lines that are not part of the report.

CI mode reads `hoglint compare --all` or `hoglint check --all`. It prints a warning annotation
for each row on a line the pull request changes. The step summary shows compare's own new
findings, ledger lines and code growth, the annotated rows, the other rows and the count of
advisory rows. With `--base`, it also prints a notice on each changed file that goes away when
hoglint replaces tach, import-linter and the crossings scanner. It always exits 0.

Hook mode (`--hook`) reads `hoglint check --index --all` and the staged diff, and prints what the
developer reads instead of hoglint's output. It exits 1 to block the commit, and 0 otherwise.
A row on a staged line blocks. New ledger debt or a new exception blocks when the commit also
stages other files. hoglint judges ledger growth, except when a policy file is staged, because
hoglint then skips that check; the script then reads the staged ledger diff itself.

    hoglint_shadow.py <stdout file> --stderr <file> --status <exit> --until "<date>" [--base HEAD^1]
    hoglint_shadow.py <stdout file> --stderr <file> --status <exit> --hook
"""

from __future__ import annotations

import os
import re
import secrets
import argparse
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:
    # The hook's last-resort `python3` can predate 3.11. The exceptions check then compares text.
    tomllib = None  # type: ignore[assignment]

# A finding is a headline, `<rule>: <message>`, then more indented lines. The first of them is its
# place, `at <site>` with optional owners, `  [team, ...]`, after it. The site is
# `<path>:<line>` or `(no line)`, and a path can hold spaces and any letters.
HEADLINE = re.compile(r"^(?P<rule>[a-z][a-z0-9-]*): (?P<message>.+)$")
PLACE = re.compile(r"^\s*at (?P<site>.+?)(?:  \[[^\]]*\])?$")
SITE = re.compile(r"^(?P<path>.+):(?P<line>\d+)$")
# An unknown is one row, `<rule> [<cause>, <kind>] <place>: <reason>`, and the place is optional.
UNKNOWN = re.compile(r"^(?P<rule>\S+) \[(?P<cause>[a-z-]+), (?P<kind>[a-z-]+)\] (?P<rest>.*)$")
UNKNOWN_AT_LINE = re.compile(r"^(?P<path>.+?):(?P<line>\d+): (?P<reason>.*)$")
UNKNOWN_AT_FILE = re.compile(r"^(?P<path>[^:]*(?:/|\.py)[^:]*): (?P<reason>.*)$")
# The title of the problem that carries the ways out for unknowns of one rule and kind.
UNKNOWN_PROBLEM = re.compile(r"^\S+: (this place|each of these \d+ places) ")
LEDGER_GROWTH = re.compile(r"^This change adds \d+ lines? to .+, with no policy change\.$")
# A finding with no place line, such as a placement rule's, names its module first.
MODULE = re.compile(r"^(?P<module>[A-Za-z_][\w.]*) ")
# A section title ends with its row count, `advisory rows (898)`.
COUNT = re.compile(r"\((?P<count>\d+)\)$")
HUNK = re.compile(r"^@@ -\d+(?:,(?P<old>\d+))? \+(?P<start>\d+)(?:,(?P<new>\d+))? @@")
OCTAL = re.compile(r"[0-7]{3}")

# The causes of an unknown that the change under check added. An extractor unknown never blocks,
# because the fault is in hoglint. Inherited unknowns came before the change, and no row shows them.
CHANGE_CAUSES = ("introduced", "ambiguous")
EXTRACTOR_CAUSE = "extractor"

FINDINGS_TITLE = "new findings ("
ADVISORY_TITLE = "advisory rows ("
UNKNOWNS_TITLE = "unknowns ("
GUARD_START = "Fix each finding"
# What the full view prints before its problems: the verdict, other `hoglint:` lines and the
# count per rule.
SKIPPED_TITLES = ("hoglint: ", "New findings by rule:", GUARD_START)
# The titles the full view prints after the findings. Any other line at the line start in that
# part is not a section, so it does not end one.
LATER_TITLES = (
    ADVISORY_TITLE,
    "existing debt in touched files (advisory) (",
    UNKNOWNS_TITLE,
    "unknowns attributed against ",
    "level ",
    "note: ",
    "What the hook checks",
)
ACCEPTED_TITLE = re.compile(r"^\d+ findings? accepted by the ledger$")
COMPARE_SECTIONS = ("findings new (", "ledger lines added (", "code growth (fails) (")

LEDGER_FILE = "hoglint.ledger"
# A change to one of these makes hoglint skip its own ledger growth check.
POLICY_FILES = ("hoglint.toml", "hoglint.exceptions.toml")
POLICY_DIRS = ("tools/hoglint/",)
EXCEPTIONS_FILE = "hoglint.exceptions.toml"
# The CI step summary holds at most 1 MiB, so a long section shows its first rows and a count.
SUMMARY_ROWS = 50
OLD_TOOL_FILES = ("tach.toml", "products/model_crossing_uses_baseline.txt", "products/isolation_baseline.txt")
# pyproject.toml stays, so only an edit in its import-linter table goes away.
IMPORT_LINTER_WORDS = ("ignore_imports", "importlinter")

BLOCK_LINE = "hoglint blocks findings on the lines this commit changes. Fix them, or run `hoglint explain {rule}`."
REST_LINE = "{count} not on lines this commit changes; CI and the ledger catch-up judge them."
LEDGER_LINE = (
    f"hoglint blocks new lines in {LEDGER_FILE} when the commit also changes other files. "
    "Commit the ledger lines alone, so that a person reviews them."
)
EXCEPTION_LINE = (
    f"hoglint blocks a change to {EXCEPTIONS_FILE} when the commit also changes other files. "
    "Commit it alone, so that a person reviews it."
)
CONTINUES_LINE = "hoglint did not finish this check, so the commit continues. CI runs the full check."


@dataclass(frozen=True)
class Block:
    """A line at the line start and the indented lines under it."""

    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Row:
    """A new finding or a new unknown, with the lines hoglint prints for it. `cause` is empty for
    a finding. A row without a path or without a line has no place on a changed line."""

    rule: str
    message: str
    path: str | None
    line: int | None
    lines: tuple[str, ...]
    cause: str = ""
    module: str | None = None

    def place(self) -> str:
        if self.path is None:
            return self.module or "(no line)"
        return f"{self.path}:{self.line}" if self.line else self.path

    def is_full(self) -> bool:
        return any(line.lstrip().startswith("see: ") for line in self.lines)


@dataclass(frozen=False)
class ChangedLines:
    """The lines a diff at zero context adds or edits, per file. A new file counts whole. `added`
    names the new files, because an empty new file has no `+++` line in the diff."""

    lines: dict[str, set[int]] = field(default_factory=dict)
    new_files: set[str] = field(default_factory=set)
    added_text: dict[str, list[str]] = field(default_factory=dict)
    removed_text: dict[str, list[str]] = field(default_factory=dict)

    @staticmethod
    def of(diff: str, added: list[str] | None = None) -> ChangedLines:
        changed = ChangedLines(new_files=set(added or []))
        path: str | None = None
        old_path: str | None = None
        is_new = False
        old_left = new_left = 0
        # git ends each diff line with `\n` alone. `splitlines` also splits on separators such as
        # U+2028 inside a line, which would throw off the hunk counts.
        for line in diff.split("\n"):
            # Inside a hunk every line is content, even one that looks like a header.
            if old_left or new_left:
                if line.startswith("-"):
                    old_left -= 1
                    if old_path is not None:
                        changed.removed_text.setdefault(old_path, []).append(line[1:])
                elif line.startswith("+"):
                    new_left -= 1
                    if path is not None:
                        changed.added_text.setdefault(path, []).append(line[1:])
                continue
            hunk = HUNK.match(line)
            if line.startswith("diff --git "):
                path, old_path, is_new = None, None, False
            elif line.startswith("new file mode"):
                is_new = True
            elif line.startswith("--- "):
                old_path = diff_path(line[4:], "a/")
            elif line.startswith("+++ "):
                path = diff_path(line[4:])
                if path is not None and is_new:
                    changed.new_files.add(path)
            elif hunk and path is not None:
                start = int(hunk["start"])
                count = int(hunk["new"]) if hunk["new"] is not None else 1
                changed.lines.setdefault(path, set()).update(range(start, start + count))
                old_left = int(hunk["old"]) if hunk["old"] is not None else 1
                new_left = count
        return changed

    def covers(self, row: Row) -> bool:
        """A whole-module finding sits on a changed line only when its module's file is new."""
        if row.path is None:
            return row.module is not None and any(path in self.new_files for path in module_files(row.module))
        if row.path in self.new_files:
            return True
        return row.line is not None and row.line in self.lines.get(row.path, set())

    def ledger_grows(self) -> bool:
        """Whether the diff adds a rule line to the ledger, or raises a count. A level line records
        a group that passes a level, which is no debt, and a lowered count is a fix."""
        removed = ledger_counts(self.removed_text.get(LEDGER_FILE, []))
        added = ledger_counts(self.added_text.get(LEDGER_FILE, []))
        return any(count > removed.get(key, 0) for key, count in added.items())


@dataclass(frozen=True)
class StagedChange:
    """What the hook reads from git: the staged diff, the staged names, and the exceptions file at
    HEAD and in the index."""

    lines: ChangedLines
    names: list[str]
    exceptions_before: str = ""
    exceptions_after: str = ""

    def alone(self, path: str) -> bool:
        return all(name == path for name in self.names)

    def stages_policy(self) -> bool:
        return any(name in POLICY_FILES or name.startswith(POLICY_DIRS) for name in self.names)

    def adds_exceptions(self) -> bool:
        """Whether the index holds an exception that HEAD does not, as data, whatever the TOML
        spelling. A removed exception is a fix, like a lowered ledger count."""
        if EXCEPTIONS_FILE not in self.names:
            return False
        if tomllib is None:
            return self.exceptions_before != self.exceptions_after
        try:
            before = tomllib.loads(self.exceptions_before).get("exception", [])
            after = tomllib.loads(self.exceptions_after).get("exception", [])
        except tomllib.TOMLDecodeError:
            return True
        return any(entry not in before for entry in after)


def module_files(module: str) -> list[str]:
    path = module.replace(".", "/")
    return [f"{path}.py", f"{path}/__init__.py"]


def ledger_counts(lines: list[str]) -> dict[str, int]:
    """Each ledger rule line's key and count. Comments and level lines are not debt."""
    out = {}
    for line in lines:
        fields = line.split("\t")
        if len(fields) < 2 or line.startswith(("#", "level:")) or not fields[-1].isdigit():
            continue
        out["\t".join(fields[:-1])] = int(fields[-1])
    return out


def unquote(quoted: str) -> str:
    """A path as git quotes it in a diff header: in double quotes, with C escapes and octal bytes."""
    body = quoted[1:-1]
    out = bytearray()
    escapes = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11, '"': 34, "\\": 92}
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\":
            out.extend(char.encode())
            index += 1
            continue
        octal = OCTAL.match(body, index + 1)
        if octal:
            out.append(int(octal.group(), 8))
            index += 4
            continue
        out.append(escapes.get(body[index + 1], ord(body[index + 1])))
        index += 2
    return out.decode(errors="replace")


def diff_path(header: str, prefix: str = "b/") -> str | None:
    """The path of a `---` or `+++` header line, without its prefix. None for `/dev/null`. git ends
    the line with a tab when the path holds a space."""
    header = header.removesuffix("\t")
    if header == "/dev/null":
        return None
    if header.startswith('"') and header.endswith('"'):
        header = unquote(header)
    return header.removeprefix(prefix)


def escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(value: str) -> str:
    return escape_data(value).replace(":", "%3A").replace(",", "%2C")


def dedent(line: str) -> str:
    return line[2:] if line.startswith("  ") else line


def is_later_title(line: str) -> bool:
    return line.startswith(LATER_TITLES) or bool(ACCEPTED_TITLE.match(line))


class FullView:
    """hoglint's full view (`--all`), read as blocks: the rows a change can own, the advisory
    count, the guard line and the problems that have no file."""

    def __init__(self, output: str) -> None:
        self.output = output
        self.blocks: list[Block] = []
        after_findings = False
        for line in output.splitlines():
            if not line.strip():
                continue
            if line.startswith(" ") and self.blocks:
                last = self.blocks[-1]
                self.blocks[-1] = Block(last.title, (*last.lines, line))
                continue
            if after_findings and not is_later_title(line):
                continue
            after_findings = after_findings or line.startswith(FINDINGS_TITLE)
            self.blocks.append(Block(line, ()))

    def block(self, title_start: str) -> Block | None:
        return next((block for block in self.blocks if block.title.startswith(title_start)), None)

    def is_report(self) -> bool:
        return self.block(FINDINGS_TITLE) is not None

    def first_line(self) -> str:
        return self.blocks[0].title if self.blocks else ""

    def findings(self) -> list[Row]:
        block = self.block(FINDINGS_TITLE)
        if block is None:
            return []
        entries: list[list[str]] = []
        for line in block.lines:
            if line.startswith("    ") and entries:
                entries[-1].append(dedent(line))
            else:
                entries.append([dedent(line)])
        rows = []
        for entry in entries:
            headline = HEADLINE.match(entry[0])
            if not headline:
                continue
            place = PLACE.match(entry[1]) if len(entry) > 1 else None
            site = SITE.match(place["site"]) if place else None
            path = site["path"] if site else None
            number = int(site["line"]) if site else None
            # A finding with no file, `at (no line)` or no place line at all, names its module.
            named = None if site else MODULE.match(headline["message"])
            module = named["module"] if named else None
            rows.append(Row(headline["rule"], headline["message"], path, number, tuple(entry), module=module))
        return rows

    def unknowns(self) -> list[Row]:
        """The unknowns a change can own or that hoglint caused, each with its own rule's ways out."""
        block = self.block(UNKNOWNS_TITLE)
        if block is None:
            return []
        rows = []
        for line in block.lines:
            unknown = UNKNOWN.match(dedent(line))
            if not unknown or unknown["cause"] not in (*CHANGE_CAUSES, EXTRACTOR_CAUSE):
                continue
            rest = unknown["rest"]
            at_line = UNKNOWN_AT_LINE.match(rest)
            at_file = None if at_line else UNKNOWN_AT_FILE.match(rest)
            if at_line:
                path, number, reason = at_line["path"], int(at_line["line"]), at_line["reason"]
                place = f"{path}:{number}"
            elif at_file:
                path, number, reason = at_file["path"], None, at_file["reason"]
                place = path
            else:
                path, number, reason, place = None, None, rest, ""
            guidance = self.unknown_guidance(unknown["rule"], place, reason)
            row = Row(unknown["rule"], reason, path, number, (dedent(line), *guidance), unknown["cause"])
            if row not in rows:
                rows.append(row)
        return rows

    def unknown_guidance(self, rule: str, place: str, reason: str) -> list[str]:
        """The why and the ways out of this rule's problem that lists this unknown's place."""
        row = f"  at {place}: {reason}" if place else f"  at {reason}"
        for block in self.blocks:
            if block.title.startswith(f"{rule}: ") and row in block.lines:
                return [line for line in block.lines if not line.startswith("  at ")]
        return []

    def rows(self) -> list[Row]:
        return [*self.findings(), *self.unknowns()]

    def rule_guidance(self, rule: str) -> list[str]:
        """The why, ways out and `see:` lines that the full view prints once, under the first
        finding of a rule."""
        for row in self.findings():
            if row.rule == rule and row.is_full():
                return [line for line in row.lines[1:] if not PLACE.match(line)]
        return [f"  see: hoglint explain {rule}"]

    def advisory_count(self) -> int:
        block = self.block(ADVISORY_TITLE)
        count = COUNT.search(block.title) if block is not None else None
        return int(count["count"]) if count else 0

    def guard(self) -> str | None:
        block = self.block(GUARD_START)
        return None if block is None else block.title

    def problems_without_file(self) -> list[Block]:
        """The problems the full view prints before the findings, except the ones for unknowns,
        which come back as rows."""
        out = []
        for block in self.blocks:
            if block.title.startswith(FINDINGS_TITLE):
                break
            if block.title.startswith(SKIPPED_TITLES) or UNKNOWN_PROBLEM.match(block.title):
                continue
            out.append(block)
        return out

    def render(self, rows: list[Row]) -> list[str]:
        """Each row with hoglint's lines for it; a finding rule's why and ways out once per rule."""
        out: list[str] = []
        explained: set[str] = set()
        for row in rows:
            out.extend(row.lines)
            if row.is_full():
                explained.add(row.rule)
            elif row.rule not in explained and not row.cause:
                out.extend(self.rule_guidance(row.rule))
                explained.add(row.rule)
            else:
                out.append(f"  see: hoglint explain {row.rule}")
        return out


class HookFilter:
    """Hook mode: a row on a changed line blocks the commit, and so do new ledger debt or a changed
    exception that come with other files. Everything else passes."""

    def __init__(self, output: str, stderr: str, status: int, change: StagedChange) -> None:
        self.view = FullView(output)
        self.stderr = stderr.rstrip()
        self.status = status
        self.change = change

    def verdict(self) -> tuple[int, str]:
        out = [self.stderr] if self.stderr else []
        blocking: list[Row] = []
        if self.status == 3:
            out.append(self.view.output.rstrip())
        elif self.status == 0:
            out += [block.title for block in self.view.blocks if block.title.startswith(("hoglint: ", "note: "))]
        elif not self.view.is_report():
            out += [line for line in (self.view.first_line(), CONTINUES_LINE) if line]
        else:
            rows = self.view.rows()
            blocking = [row for row in rows if row.cause != EXTRACTOR_CAUSE and self.change.lines.covers(row)]
            out += self.rows_text(blocking, [row for row in rows if row not in blocking])
        policy = self.policy_lines()
        out += policy
        return (1 if blocking or policy else 0), "\n".join(line for line in out if line)

    def ledger_grows(self) -> bool:
        """hoglint judges ledger growth, and it knows a move from new debt. With a policy file
        staged it skips that check, so the staged ledger diff decides."""
        if self.change.stages_policy():
            return self.change.lines.ledger_grows()
        return any(LEDGER_GROWTH.match(problem.title) for problem in self.view.problems_without_file())

    def policy_lines(self) -> list[str]:
        """The lines that block new ledger debt or a new exception staged with other files."""
        out = []
        if self.ledger_grows() and not self.change.alone(LEDGER_FILE):
            out.append(LEDGER_LINE)
        if self.change.adds_exceptions() and not self.change.alone(EXCEPTIONS_FILE):
            out.append(EXCEPTION_LINE)
        return out

    def rows_text(self, blocking: list[Row], rest: list[Row]) -> list[str]:
        out = self.view.render(blocking)
        guard = self.view.guard()
        if blocking and guard:
            out.append(guard)
        for problem in self.view.problems_without_file():
            out.extend([problem.title, *problem.lines])
        out += self.view.render([row for row in rest if row.cause == EXTRACTOR_CAUSE or row.path is None])
        if rest:
            count = "1 finding is" if len(rest) == 1 else f"{len(rest)} findings are"
            out.append(REST_LINE.format(count=count))
        if blocking:
            out.append(BLOCK_LINE.format(rule=blocking[0].rule))
        return out


class ShadowReport:
    """CI mode: the rows on changed lines become annotations, and the summary lists every row."""

    def __init__(self, output: str, stderr: str, status: int, until: str, changed: ChangedLines) -> None:
        self.view = FullView(output)
        self.stderr = stderr
        self.status = status
        self.until = until
        self.changed = changed

    def own_rows(self) -> list[Row]:
        return [row for row in self.view.rows() if self.changed.covers(row)]

    def other_rows(self) -> list[Row]:
        return [row for row in self.view.rows() if not self.changed.covers(row)]

    def annotations(self) -> list[str]:
        out = []
        for row in self.own_rows():
            properties = [f"file={escape_property(row.path or '')}"]
            if row.line:
                properties.append(f"line={row.line}")
            properties.append(f"title={escape_property(f'hoglint {row.rule} (shadow)')}")
            out.append(f"::warning {','.join(properties)}::{escape_data(row.message)}")
        return out

    def did_not_run(self) -> str:
        """The first line hoglint wrote, and the next one when the first only opens a list, such
        as `config error:`."""
        lines = [line.strip() for line in (self.view.output or self.stderr).splitlines() if line.strip()]
        first = " ".join(lines[:2]) if len(lines) > 1 and lines[0].endswith(":") else (lines or ["no output"])[0]
        return f"hoglint did not run (exit {self.status}): {first}"

    def summary(self) -> str:
        intro = (
            f"hoglint runs in shadow until {self.until}. "
            "It does not block yet; from then on it blocks the findings below."
        )
        if not self.view.is_report():
            return "\n".join([intro, "", *fenced([self.did_not_run()]), ""])
        parts = [intro, "", "**From this PR**", ""]
        compare = [b for b in self.view.blocks if b.title.startswith(COMPARE_SECTIONS) and b.lines]
        own = self.own_rows()
        if compare:
            parts += [*fenced([line for b in compare for line in (b.title, *first_rows(list(b.lines)))]), ""]
        if own:
            rendered = [*self.view.render(own[:SUMMARY_ROWS]), *more_rows(len(own))]
            parts += ["Rows on the lines this PR changes:", "", *fenced(rendered), ""]
        if not compare and not own:
            parts += ["- None.", ""]
        parts += ["**Not on lines this PR changes (master's debt, or reached through other files)**", ""]
        others = [f"{row.rule} at {row.place()}: {row.message}" for row in self.other_rows()]
        parts += fenced(first_rows(others)) if others else ["- None."]
        parts += ["", f"Advisory rows, which never block: {self.view.advisory_count()}.", ""]
        return "\n".join(line.replace("\t", " ") for line in parts)


def more_rows(total: int) -> list[str]:
    """The line that counts the rows a summary section leaves out; the log holds them all."""
    return [f"and {total - SUMMARY_ROWS} more (full list in the log)"] if total > SUMMARY_ROWS else []


def fenced(lines: list[str]) -> list[str]:
    """A text block. hoglint echoes string literals from the code it reads, so the fence is longer
    than any backtick run in the lines, and no line can close it early."""
    longest = max((len(run) for line in lines for run in re.findall(r"`+", line)), default=0)
    fence = "`" * max(3, longest + 1)
    return [f"{fence}text", *lines, fence]


def first_rows(rows: list[str]) -> list[str]:
    return [*rows[:SUMMARY_ROWS], *more_rows(len(rows))]


class OldToolEdits:
    def __init__(self, changed_paths: list[str], pyproject_diff: str, until: str) -> None:
        self.changed_paths = changed_paths
        self.pyproject_diff = pyproject_diff
        self.until = until

    def paths(self) -> list[str]:
        out = [path for path in self.changed_paths if path in OLD_TOOL_FILES]
        if "pyproject.toml" in self.changed_paths and any(w in self.pyproject_diff for w in IMPORT_LINTER_WORDS):
            out.append("pyproject.toml")
        return out

    def notices(self) -> list[str]:
        message = (
            f"This file goes away on {self.until}, when hoglint replaces tach, import-linter and the "
            "crossings scanner. After that, drop this edit when you rebase; hoglint needs no line here."
        )
        return [f"::notice file={escape_property(path)}::{escape_data(message)}" for path in self.paths()]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def git_names(*args: str) -> list[str]:
    return [name for name in git("diff", "--name-only", "-z", *args).split("\0") if name]


def git_file(revision: str) -> str:
    """A file at a revision, or empty text when it does not exist there."""
    result = subprocess.run(["git", "show", revision], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def git_diff(*args: str) -> str:
    """The diff at zero context, with fixed path prefixes whatever the user's git config says."""
    flags = ["-U0", "--inter-hunk-context=0", "-M", "--no-color", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/"]
    return git("-c", "core.quotePath=false", "diff", *flags, *args)


def read(path: Path | None) -> str:
    return path.read_text(errors="replace") if path is not None and path.exists() else ""


def run_hook(args: argparse.Namespace) -> int:
    """Exit 0 lets the commit through and 1 blocks it. On any other exit the filter failed, and
    the hook lets the commit through."""
    names = git_names("--cached")
    lines = ChangedLines.of(git_diff("--cached"), git_names("--cached", "--diff-filter=A"))
    change = StagedChange(lines, names)
    if EXCEPTIONS_FILE in names:
        change = StagedChange(lines, names, git_file(f"HEAD:{EXCEPTIONS_FILE}"), git_file(f":{EXCEPTIONS_FILE}"))
    code, text = HookFilter(read(args.output), read(args.stderr), args.status, change).verdict()
    if text:
        print(text)
    return code


def report_findings(args: argparse.Namespace, changed: ChangedLines) -> None:
    output, stderr = read(args.output), read(args.stderr)
    report = ShadowReport(output, stderr, args.status, args.until, changed)
    print("::group::hoglint output")
    # hoglint prints the PR's paths as they are, and a path may hold a line break followed by a
    # workflow command, so the runner reads no command until the echo ends.
    resume = secrets.token_hex(16)
    print(f"::stop-commands::{resume}")
    try:
        print(output.rstrip())
        print(stderr.rstrip())
    finally:
        print(f"::{resume}::")
        print("::endgroup::")
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with Path(summary_file).open("a") as summary:
            summary.write(report.summary())
    for annotation in report.annotations():
        print(annotation)


def run_ci(args: argparse.Namespace) -> int:
    changed: list[str] = []
    lines = ChangedLines()
    if args.base:
        try:
            changed = git_names(args.base, "HEAD")
            lines = ChangedLines.of(git_diff(args.base, "HEAD"), git_names("--diff-filter=A", args.base, "HEAD"))
        except Exception as error:
            print(f"Could not read the changes of this pull request ({error}).")
    try:
        report_findings(args, lines)
    except Exception as error:
        print(f"Could not read hoglint's output ({error}). hoglint runs in shadow, so this step passes.")
    if changed:
        try:
            pyproject_diff = git_diff(args.base, "HEAD", "--", "pyproject.toml")
            for notice in OldToolEdits(changed, pyproject_diff, args.until).notices():
                print(notice)
        except Exception as error:
            print(f"Could not read the pyproject.toml diff ({error}).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", type=Path, help="file with hoglint's stdout, the full view (`--all`)")
    parser.add_argument("--stderr", type=Path, help="file with hoglint's stderr")
    parser.add_argument("--status", type=int, default=1, help="hoglint's exit code")
    parser.add_argument("--hook", action="store_true", help="filter by the staged diff and exit 1 to block")
    parser.add_argument("--until", default="", help="CI: the day hoglint starts to block, as people read it")
    parser.add_argument("--base", help="CI: the pull request's base commit, to find the lines it changes")
    args = parser.parse_args()
    if not args.hook:
        return run_ci(args)
    try:
        return run_hook(args)
    except Exception as error:
        # Exit 1 blocks the commit, so a failure here must not end with Python's own exit 1.
        print(f"hoglint: could not compare the findings with the staged lines ({error}).")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

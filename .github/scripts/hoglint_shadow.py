#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""Sort hoglint's new rows by the files a change touches, while hoglint runs in shadow.

In shadow CI does not block, so master can carry findings that the ledger does not record yet.
Every later check then reports them, and only the rows in the changed files belong to the change.
The script reads the full view (`--all`), because the default view can cut the list short.

CI mode reads `hoglint compare --all` or `hoglint check --all`. It prints a warning annotation
for each row in a file the pull request changes, and writes those rows, the other rows and the
count of advisory rows to the step summary. With `--base`, it also prints a notice on each
changed file that goes away when hoglint replaces tach, import-linter and the crossings scanner.
It always exits 0.

Hook mode (`--hook`) reads `hoglint check --index --all` and the staged files, and prints what
the developer reads instead of hoglint's output. It exits 1 when a new finding, or an unknown the
change introduced, sits in a staged file, and 0 otherwise.

    hoglint_shadow.py <hoglint output file> --until "<date>" [--base HEAD^1]
    hoglint_shadow.py <hoglint output file> --hook
"""

from __future__ import annotations

import os
import re
import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

# The full view puts each section title at the line start and indents the rows under it. A
# finding row is a headline, `<rule>: <message>`, then more indented lines: its place,
# `at <path>:<line>` with optional owners after it, and for the first finding of a rule the
# rule's why, ways out and `see:` line.
HEADLINE = re.compile(r"^(?P<rule>[a-z][a-z0-9-]*): (?P<message>.+)$")
PLACE = re.compile(r"^\s+at (?P<path>\S+):(?P<line>\d+)(?:\s|$)")
# An unknown is one row, `<rule> [<cause>, <kind>] <place>: <reason>`. The place is optional and
# is a file, a file and line, or a module.
UNKNOWN = re.compile(r"^(?P<rule>\S+) \[(?P<cause>[a-z-]+), [a-z-]+\](?: (?P<place>\S+):)? (?P<reason>.*)$")
FILE_AND_LINE = re.compile(r"^(?P<path>.+):(?P<line>\d+)$")
# A section title ends with its row count, `advisory rows (898)`.
COUNT = re.compile(r"\((?P<count>\d+)\)$")
# The title of the problem that carries the ways out for blocking unknowns of one rule and kind.
UNKNOWN_PROBLEM = re.compile(r"^\S+: (this place|each of these \d+ places) ")
# The causes of an unknown that the change under check added. The others came before it.
CHANGE_CAUSES = ("introduced", "ambiguous")

FINDINGS_TITLE = "new findings ("
ADVISORY_TITLE = "advisory rows ("
UNKNOWNS_TITLE = "unknowns ("
GUARD_START = "Fix each finding"
# What the full view prints before its problems: the verdict, other `hoglint:` notes such as an
# empty pack memo, the count per rule and the guard line.
SKIPPED_TITLES = ("hoglint: ", "New findings by rule:", GUARD_START)

OLD_TOOL_FILES = ("tach.toml", "products/model_crossing_uses_baseline.txt", "products/isolation_baseline.txt")
# pyproject.toml stays, so only an edit in its import-linter table goes away.
IMPORT_LINTER_WORDS = ("ignore_imports", "importlinter")

BLOCK_LINE = "hoglint blocks findings in the files you commit. Fix them, or run `hoglint explain {rule}`."
REST_LINE = (
    "{count} in files you do not commit came from master; the ledger catches up there. "
    "Full list: hoglint check --index --all."
)


@dataclass(frozen=True)
class Block:
    """A line at the line start and the indented lines under it."""

    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Row:
    """A new finding, or an unknown the change introduced, with the lines hoglint prints for it."""

    rule: str
    message: str
    path: str
    line: int | None
    lines: tuple[str, ...]

    def place(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path

    def is_full(self) -> bool:
        return any(line.lstrip().startswith("see: ") for line in self.lines)


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(value: str) -> str:
    return escape_data(value).replace(":", "%3A").replace(",", "%2C")


def dedent(line: str) -> str:
    return line[2:] if line.startswith("  ") else line


class FullView:
    """hoglint's full view (`--all`), read as blocks: the rows a change can own, the advisory
    count, the guard line and the problems that have no file."""

    def __init__(self, output: str) -> None:
        self.output = output
        self.blocks: list[Block] = []
        for line in output.splitlines():
            if line.startswith(" ") and self.blocks:
                last = self.blocks[-1]
                self.blocks[-1] = Block(last.title, (*last.lines, line))
            elif line:
                self.blocks.append(Block(line, ()))

    def block(self, title_start: str) -> Block | None:
        return next((block for block in self.blocks if block.title.startswith(title_start)), None)

    def is_report(self) -> bool:
        return self.block(FINDINGS_TITLE) is not None

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
            place = next((PLACE.match(line) for line in entry[1:] if PLACE.match(line)), None)
            if headline and place:
                rows.append(Row(headline["rule"], headline["message"], place["path"], int(place["line"]), tuple(entry)))
        return rows

    def unknowns(self) -> list[Row]:
        block = self.block(UNKNOWNS_TITLE)
        if block is None:
            return []
        rows = []
        for line in block.lines:
            unknown = UNKNOWN.match(dedent(line))
            if not unknown or unknown["cause"] not in CHANGE_CAUSES or not unknown["place"]:
                continue
            file_and_line = FILE_AND_LINE.match(unknown["place"])
            path = file_and_line["path"] if file_and_line else unknown["place"]
            number = int(file_and_line["line"]) if file_and_line else None
            guidance = self.unknown_guidance(unknown["place"], unknown["reason"])
            rows.append(Row(unknown["rule"], unknown["reason"], path, number, (dedent(line), *guidance)))
        return rows

    def unknown_guidance(self, place: str, reason: str) -> list[str]:
        """The why and the ways out of the problem that lists this unknown's place."""
        row = f"  at {place}: {reason}"
        for block in self.blocks:
            if row in block.lines:
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
        """The problems the full view prints before the findings, except the ones for blocking
        unknowns, which come back as rows."""
        out = []
        for block in self.blocks:
            if block.title.startswith(FINDINGS_TITLE):
                break
            if block.title.startswith(SKIPPED_TITLES) or UNKNOWN_PROBLEM.match(block.title):
                continue
            out.append(block)
        return out

    def render(self, rows: list[Row]) -> list[str]:
        """Each row with hoglint's lines for it; the rule's why and ways out once per rule."""
        out: list[str] = []
        explained: set[str] = set()
        for row in rows:
            out.extend(row.lines)
            if row.is_full():
                explained.add(row.rule)
            elif row.rule not in explained:
                out.extend(self.rule_guidance(row.rule))
                explained.add(row.rule)
            else:
                out.append(f"  see: hoglint explain {row.rule}")
        return out


class HookFilter:
    """Hook mode: a row in a staged file blocks the commit. Rows elsewhere came from master."""

    def __init__(self, output: str, staged: set[str]) -> None:
        self.view = FullView(output)
        self.staged = staged

    def verdict(self) -> tuple[int, str]:
        if not self.view.is_report():
            return 0, self.view.output.rstrip()
        rows = self.view.rows()
        blocking = [row for row in rows if row.path in self.staged]
        rest = [row for row in rows if row.path not in self.staged]
        out = self.view.render(blocking)
        guard = self.view.guard()
        if blocking and guard:
            out.append(guard)
        for problem in self.view.problems_without_file():
            out.extend([problem.title, *problem.lines])
        if rest:
            out.append(REST_LINE.format(count=plural(len(rest), "finding")))
        if blocking:
            out.append(BLOCK_LINE.format(rule=blocking[0].rule))
        if not out:
            out.append(self.view.blocks[0].title)
        return (1 if blocking else 0), "\n".join(out)


class ShadowReport:
    """CI mode: the rows in the changed files become annotations, and the summary lists every row."""

    def __init__(self, output: str, until: str, changed: set[str]) -> None:
        self.view = FullView(output)
        self.until = until
        self.changed = changed

    def own_rows(self) -> list[Row]:
        return [row for row in self.view.rows() if row.path in self.changed]

    def master_rows(self) -> list[Row]:
        return [row for row in self.view.rows() if row.path not in self.changed]

    def annotations(self) -> list[str]:
        out = []
        for row in self.own_rows():
            properties = [f"file={escape_property(row.path)}"]
            if row.line:
                properties.append(f"line={row.line}")
            properties.append(f"title={escape_property(f'hoglint {row.rule} (shadow)')}")
            out.append(f"::warning {','.join(properties)}::{escape_data(row.message)}")
        return out

    def summary(self) -> str:
        intro = (
            f"hoglint runs in shadow until {self.until}. "
            "It does not block yet; from then on it blocks the findings below."
        )
        own = self.own_rows()
        parts = [intro, "", "**From this PR**", ""]
        parts += ["```text", *self.view.render(own), "```"] if own else ["- None."]
        parts += ["", "**Not from this PR (master's, until the ledger catches up)**", ""]
        parts += [f"- `{row.rule}` at `{row.place()}`: {row.message}" for row in self.master_rows()] or ["- None."]
        parts += ["", f"Advisory rows, which never block: {self.view.advisory_count()}.", ""]
        return "\n".join(parts)


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


def git_lines(*args: str) -> list[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.splitlines()


def run_hook(output_file: Path) -> int:
    """Exit 0 lets the commit through and 1 blocks it. On any other exit the filter failed, and
    the hook lets the commit through."""
    staged = set(git_lines("diff", "--cached", "--name-only"))
    code, text = HookFilter(output_file.read_text(errors="replace"), staged).verdict()
    print(text)
    return code


def report_findings(output_file: Path, until: str, changed: set[str]) -> None:
    output = output_file.read_text(errors="replace")
    report = ShadowReport(output, until, changed)
    print("::group::hoglint output")
    print(output.rstrip())
    print("::endgroup::")
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with Path(summary_file).open("a") as summary:
            summary.write(report.summary())
    for annotation in report.annotations():
        print(annotation)


def run_ci(output_file: Path, until: str, base: str | None) -> int:
    changed: list[str] = []
    if base:
        try:
            changed = git_lines("diff", "--name-only", base, "HEAD")
        except Exception as error:
            print(f"Could not list the files this pull request changes ({error}).")
    try:
        report_findings(output_file, until, set(changed))
    except Exception as error:
        print(f"Could not read hoglint's output ({error}). hoglint runs in shadow, so this step passes.")
    if base and changed:
        try:
            pyproject_diff = "\n".join(git_lines("diff", base, "HEAD", "--", "pyproject.toml"))
            for notice in OldToolEdits(changed, pyproject_diff, until).notices():
                print(notice)
        except Exception as error:
            print(f"Could not read the pyproject.toml diff ({error}).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", type=Path, help="file with hoglint's full view (`--all`)")
    parser.add_argument("--hook", action="store_true", help="filter by the staged files and exit 1 to block")
    parser.add_argument("--until", default="", help="CI: the day hoglint starts to block, as people read it")
    parser.add_argument("--base", help="CI: the pull request's base commit, to find the files it changes")
    args = parser.parse_args()
    if not args.hook:
        return run_ci(args.output, args.until, args.base)
    try:
        return run_hook(args.output)
    except Exception as error:
        # Exit 1 blocks the commit, so a failure here must not end with Python's own exit 1.
        print(f"hoglint: could not compare the findings with the staged files ({error}).")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

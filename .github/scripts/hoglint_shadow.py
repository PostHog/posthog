#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""Show hoglint's findings on a pull request while hoglint runs in shadow, and never fail.

Reads the text output of `hoglint compare` or `hoglint check` from a file. Prints one warning
annotation for each finding that has a location, and writes the whole output to the step
summary. With `--base`, it also prints a notice on each changed file that goes away when hoglint
replaces tach, import-linter and the crossings scanner. It always exits 0.

    hoglint_shadow.py <hoglint output file> --until "<date>" [--base HEAD^1]
"""

from __future__ import annotations

import os
import re
import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

# hoglint prints a finding as a headline, `<rule>: <message>`, and on the next line its place,
# `  at <path>:<line>` with optional owners after it.
HEADLINE = re.compile(r"^(?P<rule>[a-z][a-z0-9-]*): (?P<message>.+)$")
PLACE = re.compile(r"^  at (?P<path>\S+):(?P<line>\d+)(?:\s|$)")

OLD_TOOL_FILES = ("tach.toml", "products/model_crossing_uses_baseline.txt", "products/isolation_baseline.txt")
# pyproject.toml stays, so only an edit in its import-linter table goes away.
IMPORT_LINTER_WORDS = ("ignore_imports", "importlinter")


@dataclass(frozen=True)
class Finding:
    rule: str
    message: str
    path: str
    line: int


def escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(value: str) -> str:
    return escape_data(value).replace(":", "%3A").replace(",", "%2C")


class ShadowReport:
    def __init__(self, output: str, until: str) -> None:
        self.output = output
        self.until = until

    def findings(self) -> list[Finding]:
        """Each finding once, in output order. A finding without a line has no place to annotate."""
        found: list[Finding] = []
        previous = ""
        for line in self.output.splitlines():
            place = PLACE.match(line)
            headline = HEADLINE.match(previous)
            if place and headline:
                finding = Finding(headline["rule"], headline["message"], place["path"], int(place["line"]))
                if finding not in found:
                    found.append(finding)
            previous = line
        return found

    def annotations(self) -> list[str]:
        out = []
        for finding in self.findings():
            properties = ",".join(
                [
                    f"file={escape_property(finding.path)}",
                    f"line={finding.line}",
                    f"title={escape_property(f'hoglint {finding.rule} (shadow)')}",
                ]
            )
            out.append(f"::warning {properties}::{escape_data(finding.message)}")
        return out

    def summary(self) -> str:
        intro = (
            f"hoglint runs in shadow until {self.until}. "
            "It does not block yet; from then on it blocks the findings below."
        )
        return f"{intro}\n\n```text\n{self.output.rstrip()}\n```\n"


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


def old_tool_edits(base: str, until: str) -> OldToolEdits:
    changed = git("diff", "--name-only", base, "HEAD").splitlines()
    pyproject_diff = git("diff", base, "HEAD", "--", "pyproject.toml") if "pyproject.toml" in changed else ""
    return OldToolEdits(changed, pyproject_diff, until)


def report_findings(output_file: Path, until: str) -> None:
    output = output_file.read_text(errors="replace")
    report = ShadowReport(output, until)
    print("::group::hoglint output")
    print(output.rstrip())
    print("::endgroup::")
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with Path(summary_file).open("a") as summary:
            summary.write(report.summary())
    try:
        annotations = report.annotations()
    except Exception as error:
        print(f"Could not read hoglint's findings ({error}). The raw output is above and in the step summary.")
        return
    for annotation in annotations:
        print(annotation)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", type=Path, help="file with hoglint's text output")
    parser.add_argument("--until", required=True, help="the day hoglint starts to block, as people read it")
    parser.add_argument("--base", help="the pull request's base commit, to find edits to files that go away")
    args = parser.parse_args()

    try:
        report_findings(args.output, args.until)
    except Exception as error:
        print(f"Could not read hoglint's output ({error}). hoglint runs in shadow, so this step passes.")
    if args.base:
        try:
            for notice in old_tool_edits(args.base, args.until).notices():
                print(notice)
        except Exception as error:
            print(f"Could not list the files this pull request changes ({error}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

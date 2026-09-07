#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Measure the share of added code lines in a pull request diff that are comments.

Reads a unified diff on stdin, counts the added non-blank lines in code files, and
counts how many of those are full-line comments. Writes `warn`, a one-line
`summary`, and a Markdown `body` for the shared CI report to `$GITHUB_OUTPUT`
(or to stdout when that variable is unset).

Usage:
    gh api repos/OWNER/REPO/pulls/N -H "Accept: application/vnd.github.diff" \\
        | python3 .github/scripts/check_comment_density.py
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from dataclasses import dataclass, field

WARN_RATIO = 0.25
MIN_ADDED_LINES = 50
TOP_FILES = 8

# Docstrings are not counted, so Python is measured on `#` lines only.
HASH_LANGS = {"py", "pyi", "rb"}
SLASH_LANGS = {"ts", "tsx", "js", "jsx", "mjs", "cjs", "rs", "go", "kt", "java", "swift", "c", "h", "cpp", "hog"}
SQL_LANGS = {"sql"}
CODE_LANGS = HASH_LANGS | SLASH_LANGS | SQL_LANGS

# Generated output and snapshots are not written by a person. Workflow YAML and
# shell are left out because they need prose to be readable.
EXCLUDED_PATHS = re.compile(
    r"(^\.github/|/generated/|__snapshots__/|\.ambr$|\.snap$|\.lock$|migrations/\d|\.min\.js$|/dist/|/vendor/|/node_modules/|_pb2|\.d\.ts$)"
)
DIFF_SKIP_PREFIXES = ("+++", "---", "@@", "index ", "new file", "deleted file", "similarity", "rename ", "Binary")


@dataclass(frozen=False)
class FileStats:
    path: str
    added: int = 0
    comments: int = 0


@dataclass(frozen=False)
class Report:
    added: int = 0
    comments: int = 0
    files: dict[str, FileStats] = field(default_factory=dict)

    @property
    def ratio(self) -> float:
        return self.comments / self.added if self.added else 0.0

    @property
    def warn(self) -> bool:
        return self.added >= MIN_ADDED_LINES and self.ratio > WARN_RATIO


def _extension(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def analyze(diff_text: str) -> Report:
    report = Report()
    lang = ""
    stats: FileStats | None = None
    in_block = False

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            path = raw.split(" b/", 1)[-1]
            lang = _extension(path)
            stats = None
            in_block = False
            if lang in CODE_LANGS and not EXCLUDED_PATHS.search(path):
                stats = report.files.setdefault(path, FileStats(path))
            continue
        if stats is None or raw.startswith(DIFF_SKIP_PREFIXES) or not raw.startswith("+"):
            continue
        line = raw[1:].strip()
        if not line:
            continue

        stats.added += 1
        report.added += 1
        is_comment = False
        if lang in HASH_LANGS:
            is_comment = line.startswith("#") and not line.startswith("#!")
        elif lang in SLASH_LANGS:
            if in_block:
                is_comment = True
                in_block = "*/" not in line
            elif line.startswith(("/*", "{/*")):
                is_comment = True
                in_block = "*/" not in line
            else:
                is_comment = line.startswith(("//", "*"))
        elif lang in SQL_LANGS:
            is_comment = line.startswith("--")
        if is_comment:
            stats.comments += 1
            report.comments += 1

    report.files = {p: s for p, s in report.files.items() if s.added}
    return report


def render_summary(report: Report) -> str:
    return f"{round(100 * report.ratio)}% of added code lines are comments ({report.comments} of {report.added})"


def render_body(report: Report) -> str:
    top = sorted(report.files.values(), key=lambda s: (-s.comments, s.path))[:TOP_FILES]
    top = [s for s in top if s.comments]
    lines = [
        f"This section appears when comments are more than {round(100 * WARN_RATIO)}% of the code lines a PR adds. "
        "Only full-line comments count. Docstrings, generated files, snapshots, migrations, and workflow files are left out.",
        "",
        "Comments that restate the code, record how the change came about, or narrate the next line "
        "add noise for the next reader. Keep the comments that explain a reason the code cannot show, "
        "and remove the rest. See `.agents/skills/writing-code-comments/SKILL.md` for the house rules.",
        "",
    ]
    if top:
        lines += [
            "Files with the most added comment lines:",
            "",
            "| File | Comment lines | Added lines |",
            "| --- | ---: | ---: |",
            *(f"| `{s.path}` | {s.comments} | {s.added} |" for s in top),
            "",
        ]
    lines.append("This check does not block merging. It updates on every push and clears when the share drops.")
    return "\n".join(lines)


def write_outputs(report: Report) -> None:
    summary = render_summary(report)
    body = render_body(report)
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print(f"warn={report.warn} {summary}")
        print(body)
        return
    delimiter = f"EOF-{uuid.uuid4()}"
    with open(output_path, "a") as fh:
        fh.write(f"warn={'true' if report.warn else 'false'}\n")
        fh.write(f"summary={summary}\n")
        fh.write(f"body<<{delimiter}\n{body}\n{delimiter}\n")
    print(f"warn={report.warn} {summary}")


def main() -> int:
    write_outputs(analyze(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

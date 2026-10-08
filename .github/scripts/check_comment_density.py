#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Measure the share of added code lines in a pull request diff that are comments.

Reads a unified diff on stdin, counts the added non-blank lines in code files, and
counts how many of those are full-line comments. Writes a `status` (ok, warn, or
alert), a one-line `summary`, and a Markdown `body` for the shared CI report to
`$GITHUB_OUTPUT` (or to stdout when that variable is unset).

Usage:
    gh api repos/OWNER/REPO/pulls/N -H "Accept: application/vnd.github.diff" \\
        | python3 .github/scripts/check_comment_density.py
"""

from __future__ import annotations

import os
import re
import sys
import uuid
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

# Before agent-assisted PRs were common, the median PR had about 2% comment lines.
WARN_RATIO = 0.03
ALERT_RATIO = 0.06
MIN_ADDED_LINES = 50
TOP_FILES = 8

# Docstrings are not counted, so Python is measured on `#` lines only.
HASH_LANGS = {"py", "pyi", "rb"}
SLASH_LANGS = {"ts", "tsx", "js", "jsx", "mjs", "cjs", "rs", "go", "kt", "java", "swift", "c", "h", "cpp", "hog"}
SQL_LANGS = {"sql"}
CODE_LANGS = HASH_LANGS | SLASH_LANGS | SQL_LANGS

# Workflow YAML and shell are left out because they need prose to be readable.
# Generated paths use standard lower-case separators or an `_generated_` filename.
# A narrow match keeps hand-written names that contain `Generated` in the measurement.
EXCLUDED_PATHS = re.compile(
    r"(^\.github/|(?:^|/)(?:generated[_./]|_generated_)|\.generated\.|__snapshots__/|\.ambr$|\.snap$|\.lock$|migrations/\d|\.min\.js$|/dist/|/vendor/|/node_modules/|_pb2|\.d\.ts$)"
)
DIFF_SKIP_PREFIXES = ("+++", "---", "index ", "new file", "deleted file", "similarity", "rename ", "Binary")

ParserState = Literal["block_comment", "template_literal", "triple_string"] | None


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
    def status(self) -> str:
        if self.added < MIN_ADDED_LINES or self.ratio <= WARN_RATIO:
            return "ok"
        return "alert" if self.ratio > ALERT_RATIO else "warn"


def _extension(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _is_escaped(line: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and line[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _slash_state_after_line(line: str, state: ParserState) -> ParserState:
    index = 0
    quote = ""

    while index < len(line):
        if state == "block_comment":
            if line.startswith("*/", index):
                state = None
                index += 2
                continue
            index += 1
            continue

        if state == "template_literal":
            if line[index] == "`" and not _is_escaped(line, index):
                state = None
            index += 1
            continue

        if quote:
            if line[index] == quote and not _is_escaped(line, index):
                quote = ""
            index += 1
            continue

        if line.startswith("//", index):
            return None
        if line.startswith("/*", index):
            state = "block_comment"
            index += 2
            continue
        if line[index] in "'\"":
            quote = line[index]
        elif line[index] == "`":
            state = "template_literal"
        index += 1

    return state


def _classify_slash(line: str, state: ParserState) -> tuple[bool, ParserState]:
    if state == "template_literal":
        return False, _slash_state_after_line(line, state)

    if state == "block_comment" or line.startswith(("/*", "{/*")):
        end = line.find("*/")
        is_comment = end == -1 or line[end + 2 :].strip(" }") == ""
        return is_comment, _slash_state_after_line(line, state)

    if line.startswith("//"):
        return True, None

    return False, _slash_state_after_line(line, state)


def _classify_hash(line: str, state: ParserState) -> tuple[bool, ParserState]:
    toggles = (line.count('"""') + line.count("'''")) % 2 == 1
    if state == "triple_string":
        return False, None if toggles else state
    is_comment = line.startswith("#") and not line.startswith("#!")
    return is_comment, "triple_string" if toggles else None


def _classify(lang: str, line: str, state: ParserState) -> tuple[bool, ParserState]:
    if lang in SLASH_LANGS:
        return _classify_slash(line, state)
    if lang in HASH_LANGS:
        return _classify_hash(line, state)
    if lang in SQL_LANGS:
        return line.startswith("--"), None
    return False, None


def analyze(diff_text: str) -> Report:
    report = Report()
    lang = ""
    stats: FileStats | None = None
    # The state tracks a block comment or a multi-line string across diff lines.
    state: ParserState = None

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            path = raw.split(" b/", 1)[-1]
            lang = _extension(path)
            stats = None
            state = None
            if lang in CODE_LANGS and not EXCLUDED_PATHS.search(path):
                stats = report.files.setdefault(path, FileStats(path))
            continue
        if raw.startswith("@@"):
            state = None
            continue
        if stats is None or raw.startswith(DIFF_SKIP_PREFIXES):
            continue
        # Context lines are part of the new file too, so they move the state;
        # removed lines are not and are skipped entirely.
        added = raw.startswith("+")
        if not added and not raw.startswith(" "):
            continue
        line = raw[1:].strip()
        if not line:
            continue

        is_comment, state = _classify(lang, line, state)
        if not added:
            continue

        stats.added += 1
        report.added += 1
        if is_comment:
            stats.comments += 1
            report.comments += 1

    report.files = {p: s for p, s in report.files.items() if s.added}
    return report


def markdown_cell(value: str) -> str:
    """Keep a PR-controlled path inert in the shared report.

    Git allows backticks, pipes, and control characters in a file name. A backtick
    closes the code span so the rest renders as markdown, a pipe adds table cells,
    and a newline can forge a `<!-- ci-report:section:... -->` marker. This is the
    Python side of `markdownCell` in `frontend/bin/ci-report/format.mjs`, which the
    report's other section writers already use.
    """
    return "".join(c for c in value if c not in "`|" and not unicodedata.category(c).startswith("C"))


def render_summary(report: Report) -> str:
    return f"{round(100 * report.ratio)}% of added code lines are comments ({report.comments} of {report.added})"


def render_body(report: Report) -> str:
    top = sorted(report.files.values(), key=lambda s: (-s.comments, s.path))[:TOP_FILES]
    top = [s for s in top if s.comments]
    lines = [
        f"This section warns when comments are more than {round(100 * WARN_RATIO)}% of the code lines a PR adds, "
        f"and alerts above {round(100 * ALERT_RATIO)}%. Before agent-assisted PRs, the typical share was about 2%. "
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
            *(f"| `{markdown_cell(s.path)}` | {s.comments} | {s.added} |" for s in top),
            "",
        ]
    lines.append("This check does not block merging. It updates on every push and clears when the share drops.")
    return "\n".join(lines)


def write_outputs(report: Report) -> None:
    summary = render_summary(report)
    body = render_body(report)
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print(f"status={report.status} {summary}")
        print(body)
        return
    delimiter = f"EOF-{uuid.uuid4()}"
    with open(output_path, "a") as fh:
        fh.write(f"status={report.status}\n")
        fh.write(f"summary={summary}\n")
        fh.write(f"body<<{delimiter}\n{body}\n{delimiter}\n")
    print(f"status={report.status} {summary}")


def main() -> int:
    write_outputs(analyze(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

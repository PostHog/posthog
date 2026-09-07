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
# `generated` anywhere in the path covers `/generated/`, `*.generated.ts`, and
# `generated_configs/`, which all carry a generator header over little code.
EXCLUDED_PATHS = re.compile(
    r"(^\.github/|generated|__snapshots__/|\.ambr$|\.snap$|\.lock$|migrations/\d|\.min\.js$|/dist/|/vendor/|/node_modules/|_pb2|\.d\.ts$)",
    re.IGNORECASE,
)
DIFF_SKIP_PREFIXES = ("+++", "---", "index ", "new file", "deleted file", "similarity", "rename ", "Binary")


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


def _classify_slash(line: str, in_block: bool) -> tuple[bool, bool]:
    """Return (is_comment, in_block after this line) for a `//` and `/* */` language."""
    if in_block:
        return True, "*/" not in line
    if line.startswith("//"):
        return True, False
    if line.startswith(("/*", "{/*")):
        end = line.find("*/")
        if end == -1:
            return True, True
        # `/* note */ doWork()` is code with a leading comment, not a comment line.
        return line[end + 2 :].strip(" }") == "", False
    return False, False


def _classify_hash(line: str, in_string: bool) -> tuple[bool, bool]:
    """Return (is_comment, in_string after this line) for Python.

    A `#` line inside a triple-quoted string (a prompt, a SQL template) is text,
    not a comment.
    """
    toggles = (line.count('"""') + line.count("'''")) % 2 == 1
    if in_string:
        return False, not toggles
    return line.startswith("#") and not line.startswith("#!"), toggles


def _classify(lang: str, line: str, inside: bool) -> tuple[bool, bool]:
    if lang in SLASH_LANGS:
        return _classify_slash(line, inside)
    if lang in HASH_LANGS:
        return _classify_hash(line, inside)
    if lang in SQL_LANGS:
        return line.startswith("--"), False
    return False, False


def analyze(diff_text: str) -> Report:
    report = Report()
    lang = ""
    stats: FileStats | None = None
    # True inside a block comment or a triple-quoted string that spans lines.
    inside = False

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            path = raw.split(" b/", 1)[-1]
            lang = _extension(path)
            stats = None
            inside = False
            if lang in CODE_LANGS and not EXCLUDED_PATHS.search(path):
                stats = report.files.setdefault(path, FileStats(path))
            continue
        if raw.startswith("@@"):
            inside = False
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

        is_comment, inside = _classify(lang, line, inside)
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

#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Count the test lines a pull request diff adds that assert on mock calls.

Reads a unified diff on stdin and counts, in test files only, the added and removed
lines that check whether a mock was called, how often, or with which arguments.
Writes a `status` (ok or warn), a one-line `summary`, and a Markdown `body` for the
shared CI report to `$GITHUB_OUTPUT` (or to stdout when that variable is unset).

Usage:
    gh api repos/OWNER/REPO/pulls/N -H "Accept: application/vnd.github.diff" \\
        | python3 .github/scripts/check_call_assertions.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

from check_comment_density import markdown_cell, write_github_outputs

TOP_FILES = 8

TEST_FILE = re.compile(
    r"(?:^|/)(?:tests?|__tests__)/.*\.(?:py|[cm]?[jt]sx?)$"
    r"|(?:^|/)(?:test_[^/]*|[^/]*_test|tests|conftest)\.py$"
    r"|\.(?:test|spec)\.[cm]?[jt]sx?$"
)
CALL_ASSERTION = re.compile(
    r"\b(?:toHaveBeen(?:Nth|Last)?Called\w*|toBeCalled\w*)\b"
    r"|\.mock\.(?:calls|results|lastCall)\b"
    r"|\.(?:assert_called\w*|assert_has_calls|assert_not_called|assert_any_call)\("
    r"|\.(?:call_args(?:_list)?|call_count|mock_calls)\b"
)


@dataclass(frozen=False)
class FileStats:
    path: str
    added: int = 0
    removed: int = 0

    @property
    def delta(self) -> int:
        return self.added - self.removed


@dataclass(frozen=False)
class Report:
    files: dict[str, FileStats] = field(default_factory=dict)

    @property
    def added(self) -> int:
        return sum(s.added for s in self.files.values())

    @property
    def delta(self) -> int:
        return sum(s.delta for s in self.files.values())

    @property
    def status(self) -> str:
        return "warn" if self.delta > 0 else "ok"


def analyze(diff_text: str) -> Report:
    report = Report()
    stats: FileStats | None = None
    in_hunk = False

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            path = re.split(r' "?b/', raw, maxsplit=1)[-1].rstrip('"')
            stats = FileStats(path) if TEST_FILE.search(path) else None
            in_hunk = False
            continue
        if raw.startswith("@@"):
            in_hunk = True
            continue
        if stats is None or not in_hunk or not CALL_ASSERTION.search(raw[1:]):
            continue
        if raw.startswith("+"):
            stats.added += 1
        elif raw.startswith("-"):
            stats.removed += 1
        else:
            continue
        report.files.setdefault(stats.path, stats)

    return report


def _signed(value: int) -> str:
    return f"{value:+d}"


def render_summary(report: Report) -> str:
    lines = "line asserts" if report.added == 1 else "lines assert"
    return f"{report.added} added test {lines} on mock calls (Δ {_signed(report.delta)} vs base)"


def render_body(report: Report) -> str:
    top = sorted((s for s in report.files.values() if s.added), key=lambda s: (-s.added, s.path))[:TOP_FILES]
    lines = [
        "This section warns when a PR adds more call assertions to tests than it removes. "
        "A call assertion checks that a mock was called, how often, or with which arguments, "
        "such as `toHaveBeenCalledWith` or `assert_called_once_with`.",
        "",
        "A call assertion on a collaborator inside the code under test breaks on every refactor, "
        "and it does not prove that a real receiver gets the result. "
        "Assert on the observable outcome instead, such as the response, the stored row, or the delivered message, "
        "through a real dependency or a faithful fake. Stub a dependency only to inject a fault, "
        "and still assert on the outcome.",
        "",
        "When the mock stands in for the unit's only real output, such as an outbound HTTP call, a produced message, "
        "or a queued job, its calls are the outcome rather than plumbing. "
        "A fake that records what it receives, such as a local HTTP server or an in-memory queue, "
        "checks the same outcome and survives a refactor.",
        "",
    ]
    if top:
        lines += [
            "Files with the most added call assertions:",
            "",
            "| File | Added | Δ vs base |",
            "| --- | ---: | ---: |",
            *(f"| `{markdown_cell(s.path)}` | {s.added} | {_signed(s.delta)} |" for s in top),
            "",
        ]
    lines.append(
        "This check does not block merging. It updates on every push and clears when the PR no longer adds more call assertions than it removes."
    )
    return "\n".join(lines)


def main() -> int:
    report = analyze(sys.stdin.read())
    write_github_outputs(report.status, render_summary(report), render_body(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import sys
import textwrap
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).with_name("check_comment_density.py")
SPEC = importlib.util.spec_from_file_location("check_comment_density", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
check_comment_density = importlib.util.module_from_spec(SPEC)
sys.modules["check_comment_density"] = check_comment_density
SPEC.loader.exec_module(check_comment_density)


def diff_for(path: str, body: str) -> str:
    header = (
        f"diff --git a/{path} b/{path}\nindex 0000000..1111111 100644\n--- a/{path}\n+++ b/{path}\n@@ -1,0 +1,9 @@\n"
    )
    return header + textwrap.dedent(body).lstrip("\n")


@pytest.mark.parametrize(
    "diff,expected_added,expected_comments",
    [
        pytest.param(
            diff_for(
                "posthog/api/thing.py",
                """
                +#!/usr/bin/env python3
                +# explain why
                +x = 1  # trailing comments are code lines
                +
                -# removed comment
                -removed = 2
                """,
            ),
            3,
            1,
            id="python-hash-shebang-and-removed-lines",
        ),
        pytest.param(
            diff_for(
                "frontend/src/lib/thing.ts",
                """
                +/**
                + * Block comment line
                + */
                +const a = 1 // trailing
                +// full line
                +{/* jsx style */}
                +const b = 2
                """,
            ),
            7,
            5,
            id="typescript-block-and-line-comments",
        ),
        pytest.param(
            diff_for("frontend/src/generated/api.ts", "+// generated\n+// generated\n")
            + diff_for(".github/workflows/ci.yml", "+# yaml prose\n+run: echo\n")
            + diff_for("posthog/test/__snapshots__/x.ambr", "+# name: test\n")
            + diff_for("docs/readme.md", "+<!-- not code -->\n")
            + diff_for("posthog/hogql/q.sql", "+-- sql comment\n+SELECT 1\n"),
            2,
            1,
            id="excluded-paths-and-non-code-files-are-ignored",
        ),
    ],
)
def test_analyze_counts_added_code_lines_and_full_line_comments(
    diff: str, expected_added: int, expected_comments: int
) -> None:
    report = check_comment_density.analyze(diff)
    assert (report.added, report.comments) == (expected_added, expected_comments)


@pytest.mark.parametrize(
    "code_lines,comment_lines,expected_warn",
    [
        pytest.param(10, 30, False, id="below-min-added-lines-never-warns"),
        pytest.param(40, 10, False, id="at-threshold-does-not-warn"),
        pytest.param(35, 15, True, id="above-threshold-warns"),
    ],
)
def test_warn_requires_min_size_and_ratio_above_threshold(
    code_lines: int, comment_lines: int, expected_warn: bool
) -> None:
    body = "".join("+x = 1\n" for _ in range(code_lines)) + "".join("+# c\n" for _ in range(comment_lines))
    report = check_comment_density.analyze(diff_for("posthog/a.py", body))
    assert report.warn is expected_warn


def test_render_comment_lists_marker_and_comment_heavy_files_first() -> None:
    diff = diff_for("posthog/a.py", "+# one\n+x = 1\n") + diff_for("posthog/b.py", "+# one\n+# two\n+y = 2\n")
    body = check_comment_density.render_comment(check_comment_density.analyze(diff))
    assert body.startswith(check_comment_density.COMMENT_MARKER)
    assert body.index("`posthog/b.py` | 2 | 3") < body.index("`posthog/a.py` | 1 | 2")

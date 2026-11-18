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
                +PROMPT = '''
                +# Markdown heading inside a string
                +## Use this when:
                +'''
                +# a real comment after the string
                """,
            ),
            8,
            2,
            id="python-hash-shebang-strings-and-removed-lines",
        ),
        pytest.param(
            diff_for(
                "frontend/src/lib/thing.ts",
                """
                +/**
                + * Block comment with one ` marker
                + */
                +const a = 1 // trailing
                +// full line
                +{/* jsx style */}
                +const b = 2
                +/* note */ doWork()
                +*ptr = 1
                +const snippet = `
                +// rendered SDK line
                +const escaped = \\`code\\`
                +/* rendered block */
                +`
                +const label = "Use one ` marker"
                +// real comment with one ` marker
                +// another real comment
                """,
            ),
            17,
            7,
            id="typescript-block-line-and-template-comments",
        ),
        pytest.param(
            diff_for(
                "frontend/src/lib/other.ts",
                """
                 /**
                + * doc line added inside a block that opened in context
                + */
                +const c = 3
                -/*
                +const d = 4
                """,
            ),
            4,
            2,
            id="block-state-follows-context-lines-not-removed-lines",
        ),
        pytest.param(
            diff_for("frontend/src/generated/api.ts", "+// generated\n+// generated\n")
            + diff_for("frontend/src/lib/agentScopes.generated.ts", "+// AUTO-GENERATED\n+// Do not edit\n")
            + diff_for("products/x/backend/generated_configs/ably.py", "+# generated\n+# do not edit\n")
            + diff_for("posthog/hogql/test/_generated_grammar_strategies.py", "+# generated\n+# do not edit\n")
            + diff_for(".github/workflows/ci.yml", "+# yaml prose\n+run: echo\n")
            + diff_for("posthog/test/__snapshots__/x.ambr", "+# name: test\n")
            + diff_for("docs/readme.md", "+<!-- not code -->\n")
            + diff_for("posthog/hogql/q.sql", "+-- sql comment\n+SELECT 1\n")
            + diff_for(
                "products/notebooks/frontend/NotebookNodeGeneratedWidget/index.ts",
                "+// hand-written component\n+export const widget = 1\n",
            )
            + diff_for(
                "services/mcp/tests/unit/schema-generated.test.ts",
                "+// hand-written test\n+const schema = 1\n",
            ),
            6,
            3,
            id="only-generated-paths-and-non-code-files-are-ignored",
        ),
    ],
)
def test_analyze_counts_added_code_lines_and_full_line_comments(
    diff: str, expected_added: int, expected_comments: int
) -> None:
    report = check_comment_density.analyze(diff)
    assert (report.added, report.comments) == (expected_added, expected_comments)


@pytest.mark.parametrize(
    "code_lines,comment_lines,expected_status",
    [
        pytest.param(10, 30, "ok", id="below-min-added-lines-is-always-ok"),
        pytest.param(97, 3, "ok", id="at-warn-threshold-is-ok"),
        pytest.param(96, 4, "warn", id="above-warn-threshold-warns"),
        pytest.param(94, 6, "warn", id="at-alert-threshold-warns"),
        pytest.param(93, 7, "alert", id="above-alert-threshold-alerts"),
    ],
)
def test_status_requires_min_size_and_steps_up_with_ratio(
    code_lines: int, comment_lines: int, expected_status: str
) -> None:
    body = "".join("+x = 1\n" for _ in range(code_lines)) + "".join("+# c\n" for _ in range(comment_lines))
    report = check_comment_density.analyze(diff_for("posthog/a.py", body))
    assert report.status == expected_status


def test_render_body_lists_comment_heavy_files_first() -> None:
    diff = diff_for("posthog/a.py", "+# one\n+x = 1\n") + diff_for("posthog/b.py", "+# one\n+# two\n+y = 2\n")
    body = check_comment_density.render_body(check_comment_density.analyze(diff))
    assert body.index("`posthog/b.py` | 2 | 3") < body.index("`posthog/a.py` | 1 | 2")


def test_render_body_keeps_hostile_file_paths_inert() -> None:
    diff = diff_for("posthog/x`|@user|`y.py", "+# one\n+# two\n+z = 3\n")
    body = check_comment_density.render_body(check_comment_density.analyze(diff))
    assert "| `posthog/x@usery.py` | 2 | 3 |" in body
    assert "`|" not in body


def test_block_comment_state_does_not_carry_across_hunks() -> None:
    diff = (
        "diff --git a/frontend/src/lib/thing.ts b/frontend/src/lib/thing.ts\n"
        "--- a/frontend/src/lib/thing.ts\n"
        "+++ b/frontend/src/lib/thing.ts\n"
        "@@ -1 +1 @@\n"
        "-/** old summary\n"
        "+/** new summary\n"
        "@@ -40,0 +40,2 @@\n"
        "+export const a = 1\n"
        "+export const b = 2\n"
    )
    report = check_comment_density.analyze(diff)
    assert (report.added, report.comments) == (3, 1)

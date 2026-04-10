"""Placeholder eval cases for the sandboxed coding agent.

To run:
    pytest ee/hogai/eval/sandboxed/ci/eval_basic.py

Example eval case pattern:

    1. Define a SandboxedEvalCase with prompt + expected outcomes
    2. Call SandboxedPublicEval (or SandboxedPrivateEval) with scorers
"""

from __future__ import annotations

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase, SandboxedExpected
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, FilesModified, GitDiffNonEmpty, TestsPass


@pytest.mark.django_db
async def eval_bugfix(sandbox_context, pytestconfig, posthog_client):
    cases = [
        SandboxedEvalCase(
            name="fix_divide_bug",
            prompt="The divide function in calculator.py returns wrong results. Fix the bug so all tests pass.",
            repo_fixture="bugfix_calculator",
            expected=SandboxedExpected(
                files_modified=["calculator.py"],
                tests_should_pass=True,
            ),
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-bugfix",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            GitDiffNonEmpty(),
            FilesModified(),
            TestsPass(),
        ],
        pytestconfig=pytestconfig,
        sandbox_context=sandbox_context,
        posthog_client=posthog_client,
    )

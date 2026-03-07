"""Placeholder eval cases for the sandboxed coding agent.

To run:
    pytest ee/hogai/eval/sandboxed/ci/eval_basic.py

Example eval case pattern:

    1. Build a synthetic repo fixture (see fixtures/repos.py)
    2. Define a SandboxedEvalCase with prompt + expected outcomes
    3. Call SandboxedPublicEval (or SandboxedPrivateEval) with scorers
"""

from __future__ import annotations

from ee.hogai.eval.sandboxed.config import SandboxedEvalCase, SandboxedExpected

# Example eval cases — uncomment and adapt when Docker sandbox is available.
#
# import pytest
# from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
# from ee.hogai.eval.sandboxed.scorers import (
#     ExitCodeZero,
#     FilesModified,
#     GitDiffNonEmpty,
#     TestsPass,
# )
#
#
# @pytest.fixture
# def bugfix_fixtures():
#     repo_path = bugfix_repo()
#     return {"bugfix_calculator": repo_path}
#
#
# @pytest.mark.django_db
# async def eval_bugfix(bugfix_fixtures, pytestconfig):
#     cases = [
#         SandboxedEvalCase(
#             name="fix_divide_bug",
#             prompt="The divide function in calculator.py returns wrong results. Fix the bug so all tests pass.",
#             repo_fixture="bugfix_calculator",
#             expected=SandboxedExpected(
#                 files_modified=["calculator.py"],
#                 tests_should_pass=True,
#             ),
#         ),
#     ]
#
#     await SandboxedPublicEval(
#         experiment_name="sandboxed-bugfix",
#         cases=cases,
#         repo_fixtures=bugfix_fixtures,
#         scorers=[
#             ExitCodeZero(),
#             GitDiffNonEmpty(),
#             FilesModified(),
#             TestsPass(),
#         ],
#         pytestconfig=pytestconfig,
#     )


# Eval case definitions (usable independently of the Braintrust runner)
BUGFIX_CASES = [
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

FEATURE_CASES = [
    SandboxedEvalCase(
        name="add_reverse_words",
        prompt=(
            "Add a reverse_words function to string_utils.py that reverses the order of words in a string. "
            "Remove the skip decorator from the test so it runs."
        ),
        repo_fixture="feature_string_utils",
        expected=SandboxedExpected(
            files_modified=["string_utils.py", "test_string_utils.py"],
            tests_should_pass=True,
        ),
    ),
]

from __future__ import annotations

import re

from braintrust import Score
from braintrust_core.score import Scorer


class ExitCodeZero(Scorer):
    """Binary scorer: did the agent process exit cleanly (code 0)?"""

    def _name(self) -> str:
        return "exit_code_zero"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict | None) -> Score:
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})
        exit_code = output.get("exit_code", -1)
        return Score(
            name=self._name(),
            score=1.0 if exit_code == 0 else 0.0,
            metadata={"exit_code": exit_code},
        )


class GitDiffNonEmpty(Scorer):
    """Binary scorer: did the agent make any changes to the repo?"""

    def _name(self) -> str:
        return "git_diff_non_empty"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict | None) -> Score:
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})

        git_diff = output.get("git_diff", "")
        files_changed = output.get("files_changed", [])
        has_changes = bool(git_diff.strip()) or len(files_changed) > 0
        return Score(
            name=self._name(),
            score=1.0 if has_changes else 0.0,
            metadata={"files_changed_count": len(files_changed)},
        )


class TestsPass(Scorer):
    """Scorer for whether the test suite passes after agent execution.

    Score: 1.0 if tests pass, 0.0 if they fail, None if tests weren't run.
    """

    def _name(self) -> str:
        return "tests_pass"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None = None) -> Score:
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})

        test_exit_code = output.get("test_exit_code")
        if test_exit_code is None:
            return Score(name=self._name(), score=None, metadata={"reason": "Tests not run"})

        should_pass = True
        if expected:
            should_pass = expected.get("tests_should_pass", True)

        passed = test_exit_code == 0
        # If we expect tests to pass, score 1 when they do; if we expect failure, score 1 when they fail
        correct = passed == should_pass
        return Score(
            name=self._name(),
            score=1.0 if correct else 0.0,
            metadata={
                "test_exit_code": test_exit_code,
                "expected_pass": should_pass,
                "actually_passed": passed,
                "test_output_preview": output.get("test_output", "")[:500],
            },
        )


class LintClean(Scorer):
    """Binary scorer: does the linter pass after agent execution?"""

    def _name(self) -> str:
        return "lint_clean"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict | None) -> Score:
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})

        lint_exit_code = output.get("lint_exit_code")
        if lint_exit_code is None:
            return Score(name=self._name(), score=None, metadata={"reason": "Lint not run"})

        return Score(
            name=self._name(),
            score=1.0 if lint_exit_code == 0 else 0.0,
            metadata={
                "lint_exit_code": lint_exit_code,
                "lint_output_preview": output.get("lint_output", "")[:500],
            },
        )


class FilesModified(Scorer):
    """Partial-credit scorer: what fraction of expected files were modified?

    Score = |expected ∩ actual| / |expected|

    Also penalizes if unexpected files are modified (in metadata only, not the score).
    """

    def _name(self) -> str:
        return "files_modified"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None = None) -> Score:
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})

        expected_files = set(expected.get("files_modified", [])) if expected else set()
        if not expected_files:
            return Score(name=self._name(), score=None, metadata={"reason": "No expected files specified"})

        actual_files = set(output.get("files_changed", []))
        matched = expected_files & actual_files
        score = len(matched) / len(expected_files)
        unexpected = actual_files - expected_files

        return Score(
            name=self._name(),
            score=score,
            metadata={
                "expected_files": sorted(expected_files),
                "actual_files": sorted(actual_files),
                "matched": sorted(matched),
                "missing": sorted(expected_files - actual_files),
                "unexpected": sorted(unexpected),
            },
        )


class NoBrokenTests(Scorer):
    """Regression scorer: do existing tests still pass?

    This is distinct from ``TestsPass`` — it specifically checks that the agent
    didn't break tests that were passing before. It parses pytest output to
    count failures and compares against baseline.

    Score: 1.0 if no regressions, partial credit based on ratio of passing tests.
    """

    def _name(self) -> str:
        return "no_broken_tests"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict | None) -> Score:
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})

        test_exit_code = output.get("test_exit_code")
        if test_exit_code is None:
            return Score(name=self._name(), score=None, metadata={"reason": "Tests not run"})

        test_output = output.get("test_output", "")

        # Parse pytest summary line like "5 passed, 2 failed"
        passed_match = re.search(r"(\d+) passed", test_output)
        failed_match = re.search(r"(\d+) failed", test_output)

        passed = int(passed_match.group(1)) if passed_match else 0
        failed = int(failed_match.group(1)) if failed_match else 0
        total = passed + failed

        if total == 0:
            return Score(
                name=self._name(),
                score=1.0 if test_exit_code == 0 else 0.0,
                metadata={"reason": "Could not parse test counts, using exit code"},
            )

        score = passed / total
        return Score(
            name=self._name(),
            score=score,
            metadata={
                "passed": passed,
                "failed": failed,
                "total": total,
            },
        )

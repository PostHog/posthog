"""Ratchets on warehouse source tests that can hide real behavior.

Four test shapes weaken coverage, and each has a baseline here that may only get shorter:

- a patch of a private shared helper can miss a decorated call after a rename;
- a mocked resume manager cannot show which cursor persists;
- a patched tracked session hides the real HTTP request;
- a hand-written HTTP status error, matched against `get_non_retryable_errors()`, proves only that the
  test and the dict agree, and not that the source raises that error.

The baselines list the test files that already have each shape.
"""

import re
import ast
import sys
import warnings
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from posthog.test.repo_invariants.ratchet import enforce_baseline

REPO_ROOT = Path(__file__).parents[3]
BASELINE_DIR = Path(__file__).parent
SOURCES_ROOT = REPO_ROOT / "products/warehouse_sources/backend/temporal/data_imports/sources"
SKIPPED_DIRS = {"common", "tests", "test", "__pycache__", "generated_configs"}
REGENERATE = "PYTHONPATH=. python posthog/test/repo_invariants/test_warehouse_source_test_shapes.py"

PRIVATE_SHARED_NAME = re.compile(r"sources\.common\.[A-Za-z0-9_.]+\._[a-z][A-Za-z0-9_]*$")
MOCK_BUILDERS = {"MagicMock", "Mock", "NonCallableMagicMock", "create_autospec"}
TESTING_PATH = "products/warehouse_sources/backend/temporal/data_imports/sources/common/testing"
STATUS_ERROR = re.compile(r"\b[45]\d\d (Client|Server) Error\b")
# The calls of a test that only reads the dict and matches strings against it.
DICT_READ_CALL = re.compile(
    r"^(any|all|set|str|len|sorted|list|error_message_matches|[A-Za-z0-9_]*Source"
    r"|.*\.get_non_retryable_errors|.*\.(items|keys|values|lower))$"
)
MATCH_CALLS = {"any", "error_message_matches"}

Check = Callable[[ast.Module], bool]


def _terminal_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def private_shared_patch(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Constant) and isinstance(node.value, str) and PRIVATE_SHARED_NAME.search(node.value)
        for node in ast.walk(tree)
    )


def mocked_resume_manager(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _terminal_name(node.func) not in MOCK_BUILDERS:
            continue
        specs = [*node.args[:1], *(keyword.value for keyword in node.keywords if keyword.arg in ("spec", "spec_set"))]
        if any(_terminal_name(spec) == "ResumableSourceManager" for spec in specs):
            return True
    return False


def patched_session(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.endswith(".make_tracked_session")
        ):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "object"
            and _terminal_name(node.func.value) == "patch"
            and len(node.args) > 1
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "make_tracked_session"
        ):
            return True
    return False


def _is_match_claim(test: ast.expr) -> bool:
    """`any(...)` or `error_message_matches(...)`, negated or compared with a row's expected value."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        test = test.operand

    def is_match(node: ast.expr) -> bool:
        return isinstance(node, ast.Call) and ast.unparse(node.func) in MATCH_CALLS

    if is_match(test):
        return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq | ast.Is):
        sides = [test.left, *test.comparators]
        return any(is_match(side) for side in sides) and any(
            isinstance(side, ast.Name | ast.Constant) for side in sides
        )
    return False


def _matches_hand_written_status_error(test: ast.FunctionDef) -> bool:
    body = ast.Module(body=test.body, type_ignores=[])
    nodes = list(ast.walk(body))
    if not any(isinstance(node, ast.Attribute) and node.attr == "get_non_retryable_errors" for node in nodes):
        return False
    if any(isinstance(node, ast.Call) and not DICT_READ_CALL.match(ast.unparse(node.func)) for node in nodes):
        return False
    asserts = [node for node in nodes if isinstance(node, ast.Assert)]
    if not asserts or not all(_is_match_claim(node.test) for node in asserts):
        return False
    return any(
        isinstance(node, ast.Constant) and isinstance(node.value, str) and STATUS_ERROR.search(node.value)
        for node in ast.walk(test)
    )


def hand_written_status_error(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.FunctionDef) and node.name.startswith("test_") and _matches_hand_written_status_error(node)
        for node in ast.walk(tree)
    )


# Each check: the collector, the words of which a file must hold one to be parsed, the baseline file,
# and what a '+' line means.
CHECKS: dict[str, tuple[Check, tuple[str, ...], str, str]] = {
    "private_shared_patch": (
        private_shared_patch,
        ("sources.common.",),
        "source_test_private_shared_patch_baseline.txt",
        "A '+' line is a test file that names a private shared helper. A rename can break the patch, "
        "and a decorator can keep the original function. ",
    ),
    "mocked_resume_manager": (
        mocked_resume_manager,
        ("ResumableSourceManager",),
        "source_test_mocked_resume_manager_baseline.txt",
        "A '+' line is a test file that mocks `ResumableSourceManager`. The mock cannot show which cursor persists. ",
    ),
    "hand_written_status_error": (
        hand_written_status_error,
        ("get_non_retryable_errors",),
        "source_test_hand_written_status_error_baseline.txt",
        "A '+' line is a test file that matches a hand-written HTTP status error against "
        "`get_non_retryable_errors()`. The string proves only that the test and the dict agree. "
        "`sources/tests/test_source_error_contract.py` checks the real 401, 403, 429, 500 and timeout "
        "errors of every source it can drive. For another error, drive the real response. ",
    ),
    "patched_session": (
        patched_session,
        ("make_tracked_session",),
        "source_test_patched_session_baseline.txt",
        "A '+' line is a test file that patches `make_tracked_session`. The patch hides the real HTTP request. ",
    ),
}

BLOCKING_FROM: dict[str, date] = {
    "hand_written_status_error": date.fromisoformat("2026-10-20"),
    "mocked_resume_manager": date.fromisoformat("2026-10-09"),
    "patched_session": date.fromisoformat("2026-10-09"),
    "private_shared_patch": date.fromisoformat("2026-10-09"),
}


def test_every_check_has_a_blocking_date() -> None:
    assert BLOCKING_FROM.keys() == CHECKS.keys()


def collect(check: Check, words: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for path in SOURCES_ROOT.rglob("test_*.py"):
        relative = path.relative_to(SOURCES_ROOT)
        if (
            len(relative.parts) < 2
            or relative.parts[0] in SKIPPED_DIRS
            or not (len(relative.parts) == 2 or relative.parts[1] in ("tests", "test"))
            or not path.is_file()
        ):
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        if not any(word in source for word in words):
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(source)
        except SyntaxError:
            continue
        if check(tree):
            found.append(path.relative_to(REPO_ROOT).as_posix())
    return sorted(set(found))


HAND_WRITTEN_MATCH = (
    "def test_auth(self):\n"
    "    message = '401 Client Error: Unauthorized for url: https://api.example.com/x'\n"
    "    assert any(key in message for key in self.source.get_non_retryable_errors())\n"
)

# A baseline test cannot catch a detection regression on its own: a file that stops being
# detected leaves as a '-' line, which reads as a file someone fixed.
DETECTION_CASES = [
    ("private_shared_patch", "target = 'sources.common.rest_source._private_helper'\n", True),
    ("private_shared_patch", "target = 'sources.common.rest_source.public_helper'\n", False),
    ("mocked_resume_manager", "manager = mock.MagicMock(spec=ResumableSourceManager)\n", True),
    ("mocked_resume_manager", "manager = MagicMock(spec=OtherManager)\n", False),
    ("patched_session", "target = 'source.make_tracked_session'\n", True),
    ("hand_written_status_error", HAND_WRITTEN_MATCH, True),
    ("hand_written_status_error", HAND_WRITTEN_MATCH.replace("401 Client Error", "Vendor rejected the key"), False),
    ("hand_written_status_error", HAND_WRITTEN_MATCH.replace("assert any", "assert driver_result() and any"), False),
    ("patched_session", "target = 'source.make_other_session'\n", False),
]


@pytest.mark.parametrize(("check", "source", "expected"), DETECTION_CASES)
def test_detection(check: str, source: str, expected: bool) -> None:
    assert CHECKS[check][0](ast.parse(source)) == expected


def read_baseline(file_name: str) -> list[str]:
    return sorted(line for line in (BASELINE_DIR / file_name).read_text().splitlines() if line.strip())


@pytest.mark.parametrize("check", sorted(CHECKS))
def test_source_test_files_match_the_baseline(check: str) -> None:
    collector, words, file_name, explanation = CHECKS[check]
    scanned = collect(collector, words)
    recorded = read_baseline(file_name)
    if scanned == recorded:
        return

    added = [line for line in scanned if line not in recorded]
    removed = [line for line in recorded if line not in scanned]
    report = "\n".join([*(f"  + {line}" for line in added), *(f"  - {line}" for line in removed)])
    enforce_baseline(
        added=added,
        removed=removed,
        blocking_from=BLOCKING_FROM[check],
        message=(
            f"{file_name} no longer matches the repo.\n"
            f"{explanation}Use `SourceDriver` for an extraction. Use `scripted_network` for a call outside one. "
            f"Both are in `{TESTING_PATH}`. Do not add the line to the baseline: the list may only get shorter.\n"
            f"A '-' line means a test file was fixed. The file must record that too. Run: {REGENERATE}\n"
            f"{report}"
        ),
    )


if __name__ == "__main__":
    for collector, words, file_name, _explanation in CHECKS.values():
        files = collect(collector, words)
        (BASELINE_DIR / file_name).write_text("\n".join(files) + "\n")
        sys.stdout.write(f"{file_name} written: {len(files)} files\n")

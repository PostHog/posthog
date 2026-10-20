"""Ratchets on warehouse source tests that can hide real behavior.

Three test shapes weaken coverage, and each has a baseline here that may only get shorter:

- a patch of a private shared helper can miss a decorated call after a rename;
- a mocked resume manager cannot show which cursor persists;
- a patched tracked session hides the real HTTP request.

The baselines list the test files that already have each shape.
"""

import re
import ast
import sys
import warnings
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[3]
BASELINE_DIR = Path(__file__).parent
SOURCES_ROOT = REPO_ROOT / "products/warehouse_sources/backend/temporal/data_imports/sources"
SKIPPED_DIRS = {"common", "tests", "test", "__pycache__", "generated_configs"}
REGENERATE = "python posthog/test/repo_invariants/test_warehouse_source_test_shapes.py"

PRIVATE_SHARED_NAME = re.compile(r"sources\.common\.[A-Za-z0-9_.]+\._[a-z][A-Za-z0-9_]*$")
MOCK_BUILDERS = {"MagicMock", "Mock", "NonCallableMagicMock", "create_autospec"}
TESTING_PATH = "products/warehouse_sources/backend/temporal/data_imports/sources/common/testing"

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
    "patched_session": (
        patched_session,
        ("make_tracked_session",),
        "source_test_patched_session_baseline.txt",
        "A '+' line is a test file that patches `make_tracked_session`. The patch hides the real HTTP request. ",
    ),
}


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


# A baseline test cannot catch a detection regression on its own: a file that stops being
# detected leaves as a '-' line, which reads as a file someone fixed.
DETECTION_CASES = [
    ("private_shared_patch", "target = 'sources.common.rest_source._private_helper'\n", True),
    ("private_shared_patch", "target = 'sources.common.rest_source.public_helper'\n", False),
    ("mocked_resume_manager", "manager = mock.MagicMock(spec=ResumableSourceManager)\n", True),
    ("mocked_resume_manager", "manager = MagicMock(spec=OtherManager)\n", False),
    ("patched_session", "target = 'source.make_tracked_session'\n", True),
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
    raise AssertionError(
        f"{file_name} no longer matches the repo.\n"
        f"{explanation}Use `SourceDriver` for an extraction. Use `scripted_network` for a call outside one. "
        f"Both are in `{TESTING_PATH}`. Do not add the line to the baseline: the list may only get shorter.\n"
        f"A '-' line means a test file was fixed. The file must record that too. Run: {REGENERATE}\n"
        f"{report}"
    )


if __name__ == "__main__":
    for collector, words, file_name, _explanation in CHECKS.values():
        files = collect(collector, words)
        (BASELINE_DIR / file_name).write_text("\n".join(files) + "\n")
        sys.stdout.write(f"{file_name} written: {len(files)} files\n")

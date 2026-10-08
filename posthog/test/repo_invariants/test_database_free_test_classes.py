"""Ratchet on test classes that take a database they never use.

The failure message says what a reported class means, how to confirm it, and how to
regenerate the list. `.agents/skills/writing-tests/references/database-free-test-classes.md`
carries the long form.
"""

import re
import ast
import warnings
from pathlib import Path

from parameterized import parameterized

REPO_ROOT = Path(__file__).parents[3]
BASELINE_PATH = Path(__file__).parent / "database_free_test_classes_baseline.txt"
SCANNED_ROOTS = ("posthog", "ee", "products", "common")
SKIPPED_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", ".mypy_cache"}
REGENERATE = "python posthog/test/repo_invariants/test_database_free_test_classes.py"

# Must reach a signature split over several lines and a nested class: a base it does
# not see is one that gets reported as a candidate.
CLASS_BASES = re.compile(r"^\s*class\s+\w+\s*\(([^)]*)\)", re.MULTILINE)

# Bases that bring Django `TestCase` with them. Reaching one through a project-specific
# subclass is out of scope.
POSTHOG_BASES = {
    "APIBaseTest",
    "BaseTest",
    "NonAtomicBaseTest",
    "NonAtomicBaseTestKeepIdentities",
}
# Only from django.test: a class on `unittest.TestCase` is already where this wants it.
DJANGO_BASES = {"TestCase", "TransactionTestCase"}
DATABASE_BASES = POSTHOG_BASES | DJANGO_BASES

# Any of these in the class body reads as "may reach the database". Keep it broad: an
# extra token hides a candidate, a missing one reports a class that needs its database.
DATABASE_TOKENS = (
    ".objects",
    "_create",
    "assertNumQueries",
    "bulk_create",
    "capture_db_queries",
    "connection",
    "create_",
    "cursor",
    "django_db",
    "flush_",
    "get_or_create",
    "refresh_from_db",
    "self.client",
    "self.demo_team",
    "self.organization",
    "self.other_team",
    "self.project",
    "self.team",
    "self.user",
    "snapshot",
    "transaction",
    ".delete(",
    ".exists(",
    ".filter(",
    ".save(",
)


def _django_test_names(tree: ast.Module) -> set[str]:
    """Local names bound to a django.test database base, under whatever alias.

    `from django.test import TestCase as DjangoTestCase` binds the base to a name this
    scan would otherwise not recognise, so record the local name and not the imported one.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith("django.test"):
            continue
        names.update(alias.asname or alias.name for alias in node.names if alias.name in DJANGO_BASES)
    return names


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _takes_a_database(node: ast.ClassDef, django_names: set[str]) -> bool:
    for base in node.bases:
        dotted = _dotted(base)
        if dotted is None:
            continue
        # `django.test.TestCase` written out in full reaches no import alias.
        if dotted.startswith("django.test.") and dotted.rsplit(".", 1)[-1] in DJANGO_BASES:
            return True
        if dotted in POSTHOG_BASES or dotted in django_names:
            return True
    return False


def _runs_tests(node: ast.ClassDef) -> bool:
    """A class with no test method of its own is infrastructure, not a test."""
    return any(
        isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef) and statement.name.startswith("test")
        for statement in node.body
    )


def _base_names_in_source(source: str) -> set[str]:
    return {
        base_name.strip().split("[")[0].split(".")[-1]
        for match in CLASS_BASES.finditer(source)
        for base_name in match.group(1).split(",")
    }


def _candidates_in_source(source: str) -> list[str]:
    tree = ast.parse(source)
    django_names = _django_test_names(tree)
    lines = source.splitlines()
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not _takes_a_database(node, django_names) or not _runs_tests(node):
            continue
        # Raw source, so a comment naming a table counts as a sign too.
        body = "\n".join(lines[node.lineno - 1 : node.end_lineno])
        if not any(token in body for token in DATABASE_TOKENS):
            names.append(node.name)
    return names


def collect_candidates() -> list[str]:
    # Reporting a class other tests inherit would ask for `BaseTest` itself to move to
    # `SimpleTestCase`, so gather the inherited names first and drop them at the end.
    # That gather reads every file, and has to: production code inherits from test bases,
    # so limiting it to test paths knows a fraction of the names and reports those bases.
    inherited: set[str] = set()
    found: list[tuple[str, str]] = []
    for root in SCANNED_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if SKIPPED_DIRS.intersection(path.parts):
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            inherited.update(_base_names_in_source(source))
            if not any(base in source for base in DATABASE_BASES):
                continue
            # A bad escape sequence in some other file is that file's problem, not a
            # warning this test should print.
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", SyntaxWarning)
                    names = _candidates_in_source(source)
            except SyntaxError:
                continue
            found.extend((path.relative_to(REPO_ROOT).as_posix(), name) for name in names)
    return sorted(f"{path}::{name}" for path, name in found if name not in inherited)


# Each case below is a bug this scan actually had. The baseline test cannot catch a
# detection regression on its own: a class that stops being detected leaves as a '-'
# line, which reads as a class someone fixed, and the advertised remedy is to
# regenerate the baseline.
DETECTION_CASES = [
    (
        "pure_class_on_a_posthog_base_is_reported",
        "from posthog.test.base import BaseTest\n"
        "class ExamplePure(BaseTest):\n"
        "    def test_adds(self) -> None:\n"
        "        assert 1 + 1 == 2\n",
        ["ExamplePure"],
    ),
    (
        "class_reading_a_fixture_is_left_alone",
        "from posthog.test.base import BaseTest\n"
        "class ExampleReadsTeam(BaseTest):\n"
        "    def test_named(self) -> None:\n"
        "        assert self.team.name\n",
        [],
    ),
    (
        "class_querying_a_model_is_left_alone",
        "from posthog.test.base import BaseTest\n"
        "class ExampleQueries(BaseTest):\n"
        "    def test_empty(self) -> None:\n"
        "        assert Insight.objects.count() == 0\n",
        [],
    ),
    (
        "unittest_testcase_takes_no_database",
        "from unittest import TestCase\n"
        "class ExampleUnittest(TestCase):\n"
        "    def test_adds(self) -> None:\n"
        "        assert 1 + 1 == 2\n",
        [],
    ),
    (
        "django_testcase_does_take_one",
        "from django.test import TestCase\n"
        "class ExampleDjango(TestCase):\n"
        "    def test_adds(self) -> None:\n"
        "        assert 1 + 1 == 2\n",
        ["ExampleDjango"],
    ),
    (
        "django_testcase_under_an_alias",
        "from django.test import TestCase as DjangoTestCase\n"
        "class ExampleAliased(DjangoTestCase):\n"
        "    def test_adds(self) -> None:\n"
        "        assert 1 + 1 == 2\n",
        ["ExampleAliased"],
    ),
    (
        "django_testcase_written_out_in_full",
        "import django.test\n"
        "class ExampleDotted(django.test.TestCase):\n"
        "    def test_adds(self) -> None:\n"
        "        assert 1 + 1 == 2\n",
        ["ExampleDotted"],
    ),
    (
        "class_with_no_test_method_is_infrastructure",
        "from posthog.test.base import BaseTest\n"
        "class ExampleHelpers(BaseTest):\n"
        "    def assert_ok(self, response) -> None:\n"
        "        assert response\n",
        [],
    ),
    (
        "simpletestcase_is_already_where_this_wants_it",
        "from django.test import SimpleTestCase\n"
        "class ExampleAlreadyFree(SimpleTestCase):\n"
        "    def test_adds(self) -> None:\n"
        "        assert 1 + 1 == 2\n",
        [],
    ),
]


@parameterized.expand(DETECTION_CASES)
def test_detection(_name: str, source: str, expected: list[str]) -> None:
    assert _candidates_in_source(source) == expected


BASE_NAME_CASES = [
    ("plain", "class ExampleChild(ExampleParent):\n    pass\n", "ExampleParent"),
    (
        "signature_split_over_lines",
        "class ExampleChild(\n    ExampleParent,\n    ExampleOther,\n):\n    pass\n",
        "ExampleParent",
    ),
    ("nested_in_another_class", "class Outer:\n    class Inner(ExampleParent):\n        pass\n", "ExampleParent"),
    ("dotted", "class ExampleChild(module.ExampleParent):\n    pass\n", "ExampleParent"),
]


@parameterized.expand(BASE_NAME_CASES)
def test_base_names_seen(_name: str, source: str, expected: str) -> None:
    assert expected in _base_names_in_source(source)


def test_a_base_other_tests_inherit_is_dropped() -> None:
    shared = (
        "from posthog.test.base import BaseTest\n"
        "class ExampleSharedBase(BaseTest):\n"
        "    def test_inherited_by_others(self) -> None:\n"
        "        assert self.helper()\n"
    )
    assert _candidates_in_source(shared) == ["ExampleSharedBase"]
    assert "ExampleSharedBase" in _base_names_in_source("class ExampleUser(ExampleSharedBase):\n    pass\n")


def read_baseline() -> list[str]:
    return sorted(line for line in BASELINE_PATH.read_text().splitlines() if line.strip())


def write_baseline(candidates: list[str]) -> None:
    BASELINE_PATH.write_text("\n".join(candidates) + "\n")


def test_database_free_test_classes_match_the_baseline() -> None:
    scanned = collect_candidates()
    recorded = read_baseline()
    if scanned == recorded:
        return

    added = [line for line in scanned if line not in recorded]
    removed = [line for line in recorded if line not in scanned]
    report = "\n".join([*(f"  + {line}" for line in added), *(f"  - {line}" for line in removed)])
    raise AssertionError(
        f"{BASELINE_PATH.name} no longer matches the repo.\n"
        "A '+' line is a test class that inherits a database base class but never names "
        "anything that reaches the database, so it needs a database it never reads. "
        "Confirm it by swapping the base for django.test.SimpleTestCase and running "
        "the class: SimpleTestCase refuses database access, so a passing run means the class "
        "never needed one, and that base is the fix. If the class does need a database through "
        "a helper this scan cannot see, add the baseline line back in the same change.\n"
        f"A '-' line means a candidate went away — good, but the file must record that too. Run: {REGENERATE}\n"
        f"{report}"
    )


if __name__ == "__main__":
    candidates = collect_candidates()
    write_baseline(candidates)
    print(f"baseline written: {len(candidates)} candidates")  # noqa: T201

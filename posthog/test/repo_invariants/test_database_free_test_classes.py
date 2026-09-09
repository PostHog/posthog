"""Ratchet on test classes that take a database they never use.

The failure message says what a reported class means, how to confirm it, and how to
regenerate the list. `.agents/skills/writing-tests/references/database-free-test-classes.md`
carries the long form.
"""

import re
import ast
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
BASELINE_PATH = Path(__file__).parent / "database_free_test_classes_baseline.txt"
SCANNED_ROOTS = ("posthog", "ee", "products", "common")
SKIPPED_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", ".mypy_cache"}
REGENERATE = "python posthog/test/repo_invariants/test_database_free_test_classes.py"

# Cheap enough to run over every file in the repo, unlike a full parse. `[^)]*`
# spans newlines, so a signature broken over several lines still gives up its bases,
# and the leading `\s*` reaches a nested class too.
CLASS_BASES = re.compile(r"^\s*class\s+\w+\s*\(([^)]*)\)", re.MULTILINE)

# Bases that bring Django `TestCase` with them. A class that inherits one of these
# through a project-specific subclass is out of scope, which keeps the scan cheap.
POSTHOG_BASES = {
    "APIBaseTest",
    "BaseTest",
    "NonAtomicBaseTest",
    "NonAtomicBaseTestKeepIdentities",
}
# Only from django.test: `unittest.TestCase` takes no database, so a class on that
# base is already where this scan wants it.
DJANGO_BASES = {"TestCase", "TransactionTestCase"}
DATABASE_BASES = POSTHOG_BASES | DJANGO_BASES

# Any of these in the class body is read as "this class may reach the database".
# Keep the list broad: an extra token only hides a candidate, while a missing one
# reports a class that does need its database.
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


def collect_candidates() -> list[str]:
    # A class other tests inherit names nothing itself, while every subclass reaches
    # the database, so reporting it would ask for `BaseTest` to move to
    # `SimpleTestCase`. Collect what the repo inherits from with a regex, then parse
    # only the files that could hold a candidate.
    #
    # The regex reads every file, and has to: production code inherits from test
    # bases, so a scan limited to test paths knows a fraction of the names and starts
    # reporting the bases again. It is also the cheap half. The substring check below
    # already keeps all but a handful of non-test files out of the parse, which is
    # where the time actually goes.
    #
    # A name the regex picks up wrongly only hides a candidate, which is safe; a base
    # it fails to see is the direction that reports one, so the pattern errs towards
    # taking too much.
    inherited: set[str] = set()
    found: list[tuple[str, str]] = []
    for root in SCANNED_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if SKIPPED_DIRS.intersection(path.parts):
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            for match in CLASS_BASES.finditer(source):
                for base in match.group(1).split(","):
                    inherited.add(base.strip().split("[")[0].split(".")[-1])
            if not any(base in source for base in DATABASE_BASES):
                continue
            # A bad escape sequence in some other file is that file's problem, not a
            # warning this test should print.
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", SyntaxWarning)
                    tree = ast.parse(source)
            except SyntaxError:
                continue
            django_names = _django_test_names(tree)
            lines = source.splitlines()
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if not _takes_a_database(node, django_names) or not _runs_tests(node):
                    continue
                # Raw source rather than unparsed nodes, so a comment naming a table or
                # a fixture counts as a sign the class reaches the database.
                body = "\n".join(lines[node.lineno - 1 : node.end_lineno])
                if any(token in body for token in DATABASE_TOKENS):
                    continue
                found.append((path.relative_to(REPO_ROOT).as_posix(), node.name))
    return sorted(f"{path}::{name}" for path, name in found if name not in inherited)


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

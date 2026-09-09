"""Ratchet on test classes that take a database they never use.

`BaseTest` and its relatives inherit Django `TestCase`, so one such class puts its
whole module in the lane that waits for database setup. A class that never reads or
writes a row pays that cost for nothing.

Deciding "needs a database" from source is not possible in general, because the query
can sit several helper calls deep. So this scan is deliberately conservative: it
reports a class only when the class body mentions none of DATABASE_TOKENS. A class
that does reach the database almost always names one of them, so a genuine database
test is not reported. Classes the scan misses stay missed, which is the safe error.

A reported class is a candidate, not a verdict. Confirm one before you change it:
swap its base for `django.test.SimpleTestCase` and run it. `SimpleTestCase` refuses
database access, so a passing run is proof the class never needed the database, and
the fix is to keep that base.

The list is frozen, so the count can fall but never rise. Regenerate after removing
entries (or after a rename or move):

    python posthog/test/repo_invariants/test_database_free_test_classes.py
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
BASELINE_PATH = Path(__file__).parent / "database_free_test_classes_baseline.txt"
SCANNED_ROOTS = ("posthog", "ee", "products", "common")
SKIPPED_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", ".mypy_cache"}
REGENERATE = "python posthog/test/repo_invariants/test_database_free_test_classes.py"

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
    ".exists()",
    ".filter(",
    ".save(",
)


def _django_test_names(tree: ast.Module) -> set[str]:
    """Names in this module that `django.test` supplied, under whatever alias."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("django.test"):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _takes_a_database(node: ast.ClassDef, django_names: set[str]) -> bool:
    for base in node.bases:
        if not isinstance(base, ast.Name):
            continue
        if base.id in POSTHOG_BASES or (base.id in DJANGO_BASES and base.id in django_names):
            return True
    return False


def collect_candidates() -> list[str]:
    candidates: list[str] = []
    for root in SCANNED_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if SKIPPED_DIRS.intersection(path.parts):
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            if not any(base in source for base in DATABASE_BASES):
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            django_names = _django_test_names(tree)
            lines = source.splitlines()
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef) or not _takes_a_database(node, django_names):
                    continue
                # Raw source rather than unparsed nodes, so comments count too and the
                # semgrep rule of the same name reads exactly the same text.
                body = "\n".join(lines[node.lineno - 1 : node.end_lineno])
                if any(token in body for token in DATABASE_TOKENS):
                    continue
                candidates.append(f"{path.relative_to(REPO_ROOT).as_posix()}::{node.name}")
    return sorted(candidates)


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
        "anything that reaches the database, so the module waits for database setup for "
        "nothing. Confirm it by swapping the base for django.test.SimpleTestCase and running "
        "the class: SimpleTestCase refuses database access, so a passing run means the class "
        "never needed one, and that base is the fix. If the class does need a database through "
        "a helper this scan cannot see, add the baseline line back in the same change.\n"
        f"A '-' line means a candidate went away — good, but the file must record that too. Run: {REGENERATE}\n"
        f"{report}"
    )


if __name__ == "__main__":
    write_baseline(collect_candidates())

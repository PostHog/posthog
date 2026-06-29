#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
CI + pre-commit guard: refuse to delete historical Django migration files.

A migration that already exists on master must never be deleted. Deleting the file
does not undo its schema change: the table and its constraints stay in every database
where the migration ran, fresh databases never recreate them, and the Migration Risk
Analysis job re-flags the file as a phantom new migration on every open PR that
predates the deletion. Retire a table with a state-only DeleteModel
(SeparateDatabaseAndState) plus a later DROP TABLE migration instead — both NEW files.
See docs/published/handbook/engineering/safe-django-migrations.md.

Intentional, reviewed deletions (a product/app move, a revert, a squash) are
acknowledged in .github/scripts/migration-deletion-allowlist.txt, not by disabling
this guard.

Usage:
    python3 .github/scripts/check_no_deleted_migrations.py --staged
        Pre-commit: flag staged deletions of migrations that still exist on
        origin/master. Branch-local migrations are safe to delete/regenerate.

    ... | python3 .github/scripts/check_no_deleted_migrations.py --stdin
        CI: read removed file paths (one per line) from stdin. The caller has already
        confirmed each path is removed relative to the PR base, so every migration
        among them is historical.

Exit codes:
    0 - no historical migration files deleted
    1 - one or more historical migration files would be deleted
    2 - bad usage
"""

import os
import sys
import subprocess
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_env_allowlist = os.environ.get("MIGRATION_DELETION_ALLOWLIST")
ALLOWLIST_PATH = (
    Path(_env_allowlist) if _env_allowlist else REPO_ROOT / ".github" / "scripts" / "migration-deletion-allowlist.txt"
)
BASE_REF = os.environ.get("BASE_REF", "origin/master")

# ClickHouse and async migrations are separate systems with their own safety checks;
# they live under <app>/clickhouse/migrations/ and <app>/async_migrations/migrations/.
_NON_DJANGO_PARENTS = {"clickhouse", "async_migrations"}

_GUIDANCE = """\
Deleting a migration that exists on master does NOT undo a schema change. The table
and its constraints stay in every database where the migration ran, fresh databases
never recreate them, and the Migration Risk Analysis job re-flags it as a phantom new
migration on every open PR that predates the deletion.

To retire a model/table instead:
  1. Remove all usage and the model class. Run makemigrations, then wrap the generated
     DeleteModel in migrations.SeparateDatabaseAndState(state_operations=[...]) so it
     changes Django state only. KEEP this file. Keep the app in INSTALLED_APPS.
  2. Deploy and wait at least one full deploy cycle.
  3. Optionally DROP TABLE later in a NEW RunSQL migration — never by deleting old files.

Full guide: docs/published/handbook/engineering/safe-django-migrations.md
("Dropping Tables", "Removing a whole product or app").

If this deletion is genuinely intentional and reviewed (a product/app move, a revert,
or a squash), acknowledge it by adding the path(s) to
.github/scripts/migration-deletion-allowlist.txt — never by disabling this guard.

Adding migrations is fine; deleting historical ones is not. Deleting a migration your
branch added but never merged to master is allowed (this check ignores it)."""


def is_django_migration(path: str) -> bool:
    """True for a numbered Django migration file, e.g. posthog/migrations/0001_initial.py.

    Skips the package __init__.py (not numbered) and the separate ClickHouse and
    async-migration systems.
    """
    p = PurePosixPath(path)
    if p.parent.name != "migrations" or p.suffix != ".py":
        return False
    if not p.name[:1].isdigit():  # numbered NNNN_*.py; excludes __init__.py
        return False
    return p.parent.parent.name not in _NON_DJANGO_PARENTS


def load_allowlist(allowlist_path: Path) -> list[str]:
    """Parse the deletion allowlist: one path per line, '#' comments and blanks ignored.

    A missing file is an empty allowlist, not an error.
    """
    if not allowlist_path.exists():
        return []
    entries = []
    for line in allowlist_path.read_text().splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            entries.append(entry)
    return entries


def is_allowlisted(path: str, allowlist: list[str]) -> bool:
    """True if path matches an allowlist entry exactly, or sits under a directory
    entry (one ending in '/')."""
    return any(path == entry or (entry.endswith("/") and path.startswith(entry)) for entry in allowlist)


def guarded_deletions(paths: list[str], allowlist: list[str]) -> list[str]:
    """The subset of deleted paths that are Django migrations and not allowlisted."""
    return [p for p in paths if is_django_migration(p) and not is_allowlisted(p, allowlist)]


def staged_deletions() -> list[str]:
    """Paths staged for deletion in the current index (renames decomposed to delete+add)."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=D", "--no-renames"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


def exists_on_ref(path: str, ref: str) -> bool:
    """True if path exists at the given git ref. A missing/stale ref returns False, so
    pre-commit degrades to 'cannot confirm historical' rather than failing — CI is the
    authoritative backstop."""
    return subprocess.run(["git", "cat-file", "-e", f"{ref}:{path}"], capture_output=True).returncode == 0


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "--staged"
    allowlist = load_allowlist(ALLOWLIST_PATH)

    if mode == "--stdin":
        violations = guarded_deletions(sys.stdin.read().splitlines(), allowlist)
    elif mode == "--staged":
        # Only block migrations already on master; branch-local ones are safe to delete.
        violations = [p for p in guarded_deletions(staged_deletions(), allowlist) if exists_on_ref(p, BASE_REF)]
    else:
        print(f"usage: {Path(argv[0]).name} [--staged|--stdin]", file=sys.stderr)
        return 2

    if violations:
        listed = "\n".join(f"  - {v}" for v in violations)
        print(
            f"\nERROR: refusing to delete historical Django migration file(s):\n\n{listed}\n\n{_GUIDANCE}",
            file=sys.stderr,
        )
        return 1

    print("check-no-deleted-migrations: no historical migration files deleted")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

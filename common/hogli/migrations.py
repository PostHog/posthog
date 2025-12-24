"""Django migration management for branch switching in worktrees.

This module provides commands to sync Django migrations when working across
multiple git worktrees that share the same database. It detects migrations
that are applied in the database but don't exist in the current code (orphaned),
and migrations that exist in code but aren't applied yet (pending).

Commands:
    hogli migrations:status      - Show migration diff between DB and code
    hogli migrations:down        - Roll back orphaned migrations
    hogli migrations:up          - Apply pending migrations
    hogli migrations:sync        - Smart sync: down + up in one step
    hogli migrations:cache-sync  - Populate cache from currently applied migrations

Migration File Caching:
    When migrations are applied, their files are cached to ~/.cache/posthog-migrations/.
    This allows proper rollback even after switching to a branch where the migration
    file doesn't exist. If a migration isn't cached, the tool will search git history
    and provide manual instructions.

For worktrees, simply run after switching to a worktree:
    hogli migrations:sync
"""

from __future__ import annotations

import os
import re
import sys
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import click
from hogli.core.cli import cli
from hogli.core.manifest import REPO_ROOT
from hogli.migration_utils import (
    MIGRATION_CACHE_DIR,
    get_cache_path as _get_cache_path,
    get_cached_migration as _get_cached_migration,
    get_managed_app_paths,
    hidden_conflicting_migrations,
    temporary_max_migration,
    temporary_migration_file,
)

# Pattern to match migration files (0001_initial.py, etc.)
MIGRATION_PATTERN = re.compile(r"^(\d{4})_.+\.py$")


@dataclass
class MigrationInfo:
    """Information about a single migration."""

    app: str
    name: str
    exists_in_code: bool = False
    applied_in_db: bool = False


@dataclass
class MigrationDiff:
    """Diff between database and code migration states."""

    # Migrations applied in DB but not in code (need rollback)
    orphaned: list[MigrationInfo] = field(default_factory=list)
    # Migrations in code but not applied (need apply)
    pending: list[MigrationInfo] = field(default_factory=list)
    # Migrations that are in sync
    synced: list[MigrationInfo] = field(default_factory=list)


def _cache_migration(app: str, name: str, source_path: Path) -> bool:
    """Cache a migration file for later rollback with CLI feedback."""
    from hogli.migration_utils import cache_migration_file

    if not cache_migration_file(app, name, source_path):
        click.secho(f"  ⚠ Could not cache {app}.{name}", fg="yellow", err=True)
        return False
    return True


def _find_migration_branch(app: str, name: str) -> str | None:
    """Search git history to find which branch has this migration file."""
    all_apps = get_managed_app_paths(REPO_ROOT)
    migrations_dir = all_apps.get(app)
    if not migrations_dir:
        return None

    # Get relative path from repo root
    try:
        rel_path = migrations_dir.relative_to(REPO_ROOT) / f"{name}.py"
    except ValueError:
        return None

    try:
        # Find branches that contain this file
        result = subprocess.run(
            ["git", "log", "--all", "--source", "--pretty=format:%S", "--", str(rel_path)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout.strip():
            # Return the first branch found
            branch = result.stdout.strip().split("\n")[0]
            # Clean up refs/heads/ or refs/remotes/ prefix
            if branch.startswith("refs/heads/"):
                branch = branch[len("refs/heads/") :]
            elif branch.startswith("refs/remotes/origin/"):
                branch = branch[len("refs/remotes/origin/") :]
            return branch
    except subprocess.CalledProcessError:
        # If the git command fails (e.g. not a git repo or no history), we
        # intentionally ignore the error and fall back to returning None.
        pass
    return None


def _fetch_and_cache_migration_from_git(app: str, name: str, branch: str) -> bool:
    """Fetch a migration file from a git branch and cache it.

    This allows rolling back migrations that were applied on other branches
    without having to manually switch branches.

    Returns True if successful, False otherwise.
    """
    all_apps = get_managed_app_paths(REPO_ROOT)
    migrations_dir = all_apps.get(app)
    if not migrations_dir:
        return False

    # Get relative path from repo root
    try:
        rel_path = migrations_dir.relative_to(REPO_ROOT) / f"{name}.py"
    except ValueError:
        return False

    # Try fetching from remote first (in case branch isn't checked out locally)
    for ref in [f"origin/{branch}", branch]:
        try:
            result = subprocess.run(
                ["git", "show", f"{ref}:{rel_path}"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            content = result.stdout

            # Cache the content
            cache_path = _get_cache_path(app, name)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(content)
            return True
        except subprocess.CalledProcessError:
            continue

    return False


def _get_previous_migration(app: str, migration_name: str) -> str:
    """Get the migration that should be active after rolling back the given one.

    Returns 'zero' if this is the first migration or we can't determine the previous one.

    Only considers migrations that are applied in the DB, since we're rolling back
    an applied migration and need to target another applied migration.
    """
    # Only use DB migrations - we're rolling back to another applied migration
    db_migrations = _get_migrations_in_db().get(app, set())
    all_migrations = sorted(db_migrations)

    if not all_migrations:
        return "zero"

    # Find the migration before the one we're rolling back
    try:
        idx = all_migrations.index(migration_name)
        if idx == 0:
            return "zero"
        return all_migrations[idx - 1]
    except ValueError:
        # Migration not found in DB, return zero
        return "zero"


def _get_subprocess_env() -> dict[str, str]:
    """Get environment for subprocess calls that need hogli module access."""
    env = dict(os.environ)
    env["DJANGO_SETTINGS_MODULE"] = "posthog.settings"
    # Ensure common/ is in PYTHONPATH so hogli module is importable
    common_path = str(REPO_ROOT / "common")
    existing_path = env.get("PYTHONPATH", "")
    # Use os.pathsep for cross-platform compatibility (: on Unix, ; on Windows)
    env["PYTHONPATH"] = f"{common_path}{os.pathsep}{existing_path}" if existing_path else common_path
    return env


def _run_django_migrate(app: str, target: str) -> bool:
    """Run Django migrate command. Returns True on success."""
    try:
        subprocess.run(
            [sys.executable, "manage.py", "migrate", app, target, "--no-input", "--skip-checks"],
            cwd=REPO_ROOT,
            env=_get_subprocess_env(),
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _rollback_migration_with_cache(app: str, name: str, dry_run: bool = False) -> bool:
    """Roll back a single migration using its cached file.

    Uses context managers to ensure proper cleanup of temporary files,
    hidden migrations, and max_migration.txt regardless of success or failure.
    """
    cache_path = _get_cached_migration(app, name)
    if not cache_path:
        return False

    all_apps = get_managed_app_paths(REPO_ROOT)
    migrations_dir = all_apps.get(app)
    if not migrations_dir:
        return False

    target_path = migrations_dir / f"{name}.py"
    previous = _get_previous_migration(app, name)

    if dry_run:
        click.echo(f"  [DRY RUN] Copy {cache_path} → {target_path}")
        click.echo(f"  [DRY RUN] python manage.py migrate {app} {previous}")
        click.echo(f"  [DRY RUN] Remove {target_path}")
        return True

    try:
        with (
            hidden_conflicting_migrations(migrations_dir, name),
            temporary_migration_file(cache_path, target_path),
            temporary_max_migration(migrations_dir, name),
        ):
            return _run_django_migrate(app, previous)
    except Exception as e:
        click.secho(f"  ⚠ Rollback failed for {app}.{name}: {e}", fg="red", err=True)
        return False


def _fetch_uncached_from_git(uncached: list[MigrationInfo], cached: list[MigrationInfo]) -> list[MigrationInfo]:
    """Try to fetch uncached migrations from git history.

    Moves successfully fetched migrations from uncached to cached list.
    Returns the list of migrations that are still uncached.
    """
    if not uncached:
        return []

    click.echo("Attempting to fetch uncached migrations from git…\n")
    still_uncached: list[MigrationInfo] = []

    for m in uncached:
        branch = _find_migration_branch(m.app, m.name)
        if branch:
            click.echo(f"  Fetching {m.app}.{m.name} from {branch}…")
            if _fetch_and_cache_migration_from_git(m.app, m.name, branch):
                click.secho(f"  ✓ Cached {m.app}.{m.name}", fg="green")
                cached.append(m)
            else:
                click.secho(f"  ✗ Could not fetch {m.app}.{m.name}", fg="red")
                still_uncached.append(m)
        else:
            click.secho(f"  ✗ Could not find branch for {m.app}.{m.name}", fg="red")
            still_uncached.append(m)

    click.echo()
    return still_uncached


def _show_manual_rollback_instructions(uncached: list[MigrationInfo], command_name: str) -> None:
    """Show manual rollback instructions for uncached migrations and exit."""
    click.secho("⚠ Some migrations are not cached and cannot be auto-rolled back:\n", fg="yellow")

    for m in uncached:
        branch = _find_migration_branch(m.app, m.name)
        previous = _get_previous_migration(m.app, m.name)

        click.echo(f"  {m.app}.{m.name}:")
        if branch:
            click.echo(f"    Found on branch: {branch}")
            click.echo("    To roll back properly:")
            click.echo("      1. git stash  # if you have changes")
            click.echo(f"      2. git checkout {branch}")
            click.echo(f"      3. python manage.py migrate {m.app} {previous}")
            click.echo("      4. git checkout -")
            click.echo("      5. git stash pop  # if you stashed")
        else:
            click.echo("    Could not find branch containing this migration.")
            click.echo(f"    Target migration for rollback: {m.app} {previous}")
        click.echo()

    click.echo("After manual rollback, run 'hogli migrations:sync' again.\n")
    click.echo("Or use --force to skip schema rollback (just removes DB records):")
    click.secho(f"  hogli {command_name} --force\n", fg="yellow")
    raise SystemExit(1)


def _get_migrations_in_code(app: str, migrations_dir: Path) -> set[str]:
    """Get migration names that exist in code for an app."""
    migrations: set[str] = set()
    if not migrations_dir.exists():
        return migrations

    for file in migrations_dir.iterdir():
        if file.is_file():
            match = MIGRATION_PATTERN.match(file.name)
            if match:
                # Strip .py extension
                migrations.add(file.stem)
    return migrations


def _get_database_url() -> str:
    """Get the PostgreSQL connection URL from environment."""
    # Check for explicit DATABASE_URL first
    if url := os.environ.get("DATABASE_URL"):
        return url

    # Build from individual components (PostHog's typical setup)
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    user = os.environ.get("PGUSER", "posthog")
    password = os.environ.get("PGPASSWORD", "posthog")
    database = os.environ.get("PGDATABASE", "posthog")

    return f"postgresql://{user}:{quote(password, safe='')}@{host}:{port}/{database}"


def _get_migrations_in_db() -> dict[str, set[str]]:
    """Query the database for applied migrations.

    Returns a dict mapping app labels to sets of migration names.
    Queries postgres directly for speed (bypasses Django setup).
    """
    try:
        import psycopg
    except ImportError:
        click.secho("psycopg not installed. Run: pip install psycopg", fg="red", err=True)
        raise SystemExit(1)

    try:
        db_url = _get_database_url()
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT app, name FROM django_migrations")
                rows = cur.fetchall()

        migrations: dict[str, set[str]] = {}
        for app, name in rows:
            if app not in migrations:
                migrations[app] = set()
            migrations[app].add(name)
        return migrations
    except psycopg.OperationalError as e:
        click.secho(f"Failed to connect to database: {e}", fg="red", err=True)
        raise SystemExit(1) from e
    except Exception as e:
        click.secho(f"Failed to query database: {e}", fg="red", err=True)
        raise SystemExit(1) from e


def _compute_migration_diff() -> MigrationDiff:
    """Compute the diff between database and code migration states.

    Only tracks apps that we manage (posthog, ee, rbac, products/*).
    Third-party apps (django, axes, social_django, etc.) are ignored.
    """
    diff = MigrationDiff()

    # Get all migration apps we manage
    all_apps = get_managed_app_paths(REPO_ROOT)
    managed_app_names = set(all_apps.keys())

    # Get migrations in code
    code_migrations: dict[str, set[str]] = {}
    for app, migrations_dir in all_apps.items():
        code_migrations[app] = _get_migrations_in_code(app, migrations_dir)

    # Get migrations in database (only for apps we manage)
    all_db_migrations = _get_migrations_in_db()
    db_migrations = {app: names for app, names in all_db_migrations.items() if app in managed_app_names}

    # Only process apps we manage
    for app in sorted(managed_app_names):
        in_code = code_migrations.get(app, set())
        in_db = db_migrations.get(app, set())

        # Orphaned: in DB but not in code
        for name in sorted(in_db - in_code):
            diff.orphaned.append(MigrationInfo(app=app, name=name, exists_in_code=False, applied_in_db=True))

        # Pending: in code but not in DB
        for name in sorted(in_code - in_db):
            diff.pending.append(MigrationInfo(app=app, name=name, exists_in_code=True, applied_in_db=False))

        # Synced: in both
        for name in sorted(in_code & in_db):
            diff.synced.append(MigrationInfo(app=app, name=name, exists_in_code=True, applied_in_db=True))

    return diff


def _remove_orphaned_migrations(orphaned: list[MigrationInfo], dry_run: bool = False) -> bool:
    """Remove orphaned migrations from the database.

    Since the migration files don't exist in the current code, we can't use
    Django's migrate command to roll them back. Instead, we directly delete
    the records from django_migrations table.

    WARNING: This only removes the migration record. It does NOT undo any
    schema changes the migration made. For no-op test migrations this is fine.
    For real migrations, the schema changes remain but won't cause issues
    as long as the code doesn't depend on them.
    """
    if not orphaned:
        return True

    try:
        import psycopg
    except ImportError:
        click.secho("psycopg not installed.", fg="red", err=True)
        return False

    if dry_run:
        for m in orphaned:
            click.echo(f"  [DRY RUN] DELETE FROM django_migrations WHERE app='{m.app}' AND name='{m.name}'")
        return True

    try:
        db_url = _get_database_url()
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                for m in orphaned:
                    cur.execute(
                        "DELETE FROM django_migrations WHERE app = %s AND name = %s",
                        (m.app, m.name),
                    )
                    click.echo(f"  Removed: {m.app}.{m.name}")
            conn.commit()
        return True
    except Exception as e:
        click.secho(f"Failed to remove orphaned migrations: {e}", fg="red", err=True)
        return False


def _apply_migrations(pending: list[MigrationInfo] | None = None, dry_run: bool = False) -> bool:
    """Apply all pending migrations and cache them for later rollback."""
    if dry_run:
        click.echo("  [DRY RUN] python manage.py migrate --no-input")
        return True

    try:
        subprocess.run(
            [sys.executable, "manage.py", "migrate", "--no-input"],
            cwd=REPO_ROOT,
            env=_get_subprocess_env(),
            check=True,
        )

        # Cache the migration files that were just applied
        if pending:
            all_apps = get_managed_app_paths(REPO_ROOT)
            for m in pending:
                migrations_dir = all_apps.get(m.app)
                if migrations_dir:
                    source_path = migrations_dir / f"{m.name}.py"
                    if source_path.exists():
                        _cache_migration(m.app, m.name, source_path)

        return True
    except subprocess.CalledProcessError:
        return False


@cli.command(name="migrations:status", help="Show migration diff between database and code")
def migrations_status() -> None:
    """Show which migrations are orphaned, pending, or synced."""
    click.echo("\nAnalyzing migrations…\n")

    diff = _compute_migration_diff()

    if diff.orphaned:
        click.secho("Orphaned migrations (in DB but not in code):", fg="yellow", bold=True)
        click.echo("  These were likely applied on another branch.\n")
        for m in diff.orphaned:
            click.echo(f"    {m.app}: {m.name}")
        click.echo()

    if diff.pending:
        click.secho("Pending migrations (in code but not applied):", fg="blue", bold=True)
        click.echo("  These need to be applied.\n")
        for m in diff.pending:
            click.echo(f"    {m.app}: {m.name}")
        click.echo()

    if not diff.orphaned and not diff.pending:
        click.secho("✓ Migrations are in sync", fg="green", bold=True)
        click.echo(f"  {len(diff.synced)} migration(s) applied and present in code.")
    else:
        click.echo("Run 'hogli migrations:sync' to fix, or use 'down'/'up' individually.")


@cli.command(name="migrations:down", help="Roll back orphaned migrations")
@click.option("--dry-run", "-n", is_flag=True, help="Show what would be done without executing")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
@click.option("--force", "-f", is_flag=True, help="Force removal without schema rollback (just deletes DB records)")
def migrations_down(dry_run: bool, yes: bool, force: bool) -> None:
    """Roll back migrations that are applied but don't exist in code."""
    click.echo("\nAnalyzing migrations…\n")

    if dry_run:
        click.secho("[DRY RUN MODE - No changes will be made]\n", fg="yellow")

    diff = _compute_migration_diff()

    if not diff.orphaned:
        click.secho("✓ No orphaned migrations to roll back", fg="green")
        return

    # Categorize orphaned migrations by whether we can roll them back
    cached: list[MigrationInfo] = []
    uncached: list[MigrationInfo] = []

    for m in diff.orphaned:
        if _get_cached_migration(m.app, m.name):
            cached.append(m)
        else:
            uncached.append(m)

    # Show what we found
    click.secho("Orphaned migrations to roll back:", fg="yellow", bold=True)
    for m in diff.orphaned:
        cache_status = "cached" if m in cached else "not cached"
        click.echo(f"    {m.app}: {m.name} ({cache_status})")
    click.echo()

    # Try to fetch uncached migrations from git
    if uncached and not force:
        uncached = _fetch_uncached_from_git(uncached, cached)

    # If there are still uncached migrations and not forcing, show instructions
    if uncached and not force:
        _show_manual_rollback_instructions(uncached, "migrations:down")

    # Proceed with rollback
    if not yes and not dry_run:
        if force and uncached:
            click.secho(
                "\n⚠ WARNING: --force will only remove DB records.\n"
                "Schema changes from these migrations will remain!\n",
                fg="red",
            )
        if not click.confirm("Proceed?", default=False):
            click.echo("Aborted.")
            raise SystemExit(1)

    # Roll back cached migrations properly
    if cached:
        click.echo("\nRolling back cached migrations…")
        for m in cached:
            click.echo(f"  Rolling back {m.app}.{m.name}…")
            if not _rollback_migration_with_cache(m.app, m.name, dry_run=dry_run):
                click.secho(f"  Failed to roll back {m.app}.{m.name}", fg="red")
                raise SystemExit(1)
            if not dry_run:
                click.secho(f"  ✓ Rolled back {m.app}.{m.name}", fg="green")

    # For uncached migrations (only if --force), just remove DB records
    if uncached and force:
        click.echo("\nRemoving uncached migration records (schema changes remain)…")
        if not _remove_orphaned_migrations(uncached, dry_run=dry_run):
            click.secho("Failed to remove orphaned migrations", fg="red")
            raise SystemExit(1)

    click.echo()
    click.secho("✓ Orphaned migrations handled", fg="green", bold=True)


@cli.command(name="migrations:up", help="Apply pending migrations")
@click.option("--dry-run", "-n", is_flag=True, help="Show what would be done without executing")
def migrations_up(dry_run: bool) -> None:
    """Apply migrations that exist in code but aren't applied."""
    click.echo("\nApplying pending migrations…\n")

    if dry_run:
        click.secho("[DRY RUN MODE - No changes will be made]\n", fg="yellow")

    diff = _compute_migration_diff()

    if not diff.pending:
        click.secho("✓ No pending migrations to apply", fg="green")
        return

    click.secho("Pending migrations to apply:", fg="blue", bold=True)
    for m in diff.pending:
        click.echo(f"    {m.app}: {m.name}")
    click.echo()

    if not _apply_migrations(pending=diff.pending, dry_run=dry_run):
        click.secho("Failed to apply migrations", fg="red")
        raise SystemExit(1)

    if not dry_run:
        click.secho("✓ Migrations applied and cached", fg="green", bold=True)


@cli.command(name="migrations:sync", help="Sync migrations: roll back orphaned, apply pending")
@click.option("--dry-run", "-n", is_flag=True, help="Show what would be done without executing")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
@click.option("--force", "-f", is_flag=True, help="Force sync even if some migrations can't be properly rolled back")
def migrations_sync(dry_run: bool, yes: bool, force: bool) -> None:
    """Smart sync: roll back orphaned migrations, then apply pending ones.

    This is the recommended command when switching between worktrees or branches.
    It handles both directions automatically.

    Migration files are cached when applied, enabling proper schema rollback later.
    If a migration isn't cached, instructions for manual rollback are shown.

    For worktrees, just run after cd-ing to the worktree:
        hogli migrations:sync
    """
    click.echo("\nAnalyzing migrations…\n")

    if dry_run:
        click.secho("[DRY RUN MODE - No changes will be made]\n", fg="yellow")

    diff = _compute_migration_diff()

    if not diff.orphaned and not diff.pending:
        click.secho("✓ Migrations are already in sync", fg="green", bold=True)
        click.echo(f"  {len(diff.synced)} migration(s) applied and present in code.")
        return

    # Categorize orphaned migrations
    cached: list[MigrationInfo] = []
    uncached: list[MigrationInfo] = []

    for m in diff.orphaned:
        if _get_cached_migration(m.app, m.name):
            cached.append(m)
        else:
            uncached.append(m)

    # Show what will happen
    if diff.orphaned:
        click.secho("Orphaned migrations to roll back:", fg="yellow", bold=True)
        for m in diff.orphaned:
            cache_status = "cached" if m in cached else "not cached"
            click.echo(f"    {m.app}: {m.name} ({cache_status})")
        click.echo()

    if diff.pending:
        click.secho("Pending migrations to apply:", fg="blue", bold=True)
        for m in diff.pending:
            click.echo(f"    {m.app}: {m.name}")
        click.echo()

    # Try to fetch uncached migrations from git
    if uncached and not force:
        uncached = _fetch_uncached_from_git(uncached, cached)

    # If there are still uncached migrations and not forcing, show instructions
    if uncached and not force:
        _show_manual_rollback_instructions(uncached, "migrations:sync")

    if not yes and not dry_run:
        if force and uncached:
            click.secho(
                "\n⚠ WARNING: --force will only remove DB records for uncached migrations.\n"
                "Schema changes from those migrations will remain!\n",
                fg="red",
            )
        if not click.confirm("Proceed with sync?", default=True):
            click.echo("Aborted.")
            raise SystemExit(1)

    # Step 1: Roll back orphaned migrations
    if diff.orphaned:
        click.echo("\n" + "─" * 40)
        click.secho("Step 1: Rolling back orphaned migrations", fg="yellow", bold=True)
        click.echo()

        # Roll back cached migrations properly
        for m in cached:
            click.echo(f"  Rolling back {m.app}.{m.name}…")
            if not _rollback_migration_with_cache(m.app, m.name, dry_run=dry_run):
                click.secho(f"  Failed to roll back {m.app}.{m.name}", fg="red")
                raise SystemExit(1)
            if not dry_run:
                click.secho(f"  ✓ Rolled back {m.app}.{m.name}", fg="green")

        # Remove uncached migrations (only records, if --force)
        if uncached and force:
            click.echo("\n  Removing uncached migration records…")
            if not _remove_orphaned_migrations(uncached, dry_run=dry_run):
                click.secho("Failed to remove orphaned migrations", fg="red")
                raise SystemExit(1)

    # Step 2: Apply pending
    if diff.pending:
        click.echo("\n" + "─" * 40)
        click.secho("Step 2: Applying pending migrations", fg="blue", bold=True)
        click.echo()

        if not _apply_migrations(pending=diff.pending, dry_run=dry_run):
            click.secho("Failed to apply migrations", fg="red")
            raise SystemExit(1)

        if not dry_run:
            click.secho("  ✓ Migrations applied and cached", fg="green")

    click.echo("\n" + "─" * 40)
    click.secho("✓ Sync complete", fg="green", bold=True)


@cli.command(name="migrations:cache-sync", help="Populate cache from currently applied migrations")
def migrations_cache_sync() -> None:
    """Cache all currently applied migrations that exist in code.

    This bootstraps the cache so that future rollbacks can work properly.
    Run this once after setting up hogli, or after pulling new migrations.
    """
    click.echo("\nCaching applied migrations…\n")

    diff = _compute_migration_diff()
    all_apps = get_managed_app_paths(REPO_ROOT)

    cached_count = 0
    already_cached = 0
    missing_count = 0

    for m in diff.synced:
        # Check if already cached
        if _get_cached_migration(m.app, m.name):
            already_cached += 1
            continue

        # Find the source file
        migrations_dir = all_apps.get(m.app)
        if not migrations_dir:
            missing_count += 1
            continue

        source_path = migrations_dir / f"{m.name}.py"
        if not source_path.exists():
            missing_count += 1
            continue

        # Cache it
        if _cache_migration(m.app, m.name, source_path):
            cached_count += 1
            click.echo(f"  Cached: {m.app}.{m.name}")
        else:
            click.secho(f"  Failed to cache: {m.app}.{m.name}", fg="red")

    click.echo()
    click.secho(f"✓ Cache sync complete", fg="green", bold=True)
    click.echo(f"  New: {cached_count}, Already cached: {already_cached}, Missing: {missing_count}")
    click.echo(f"  Cache location: {MIGRATION_CACHE_DIR}")

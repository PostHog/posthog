"""Custom migrate command with migration caching for worktree workflows.

Extends Django's migrate command to:
1. Check for orphaned migrations before applying new ones
2. Offer to automatically roll back orphaned migrations
3. Cache migration files after applying them for later rollback

This enables proper schema rollback when switching between branches/worktrees
that have different migrations applied.
"""

from __future__ import annotations

import os
import sys
import shutil
import warnings
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.commands.migrate import Command as DjangoMigrateCommand
from django.db import DEFAULT_DB_ALIAS
from django.db.migrations.recorder import MigrationRecorder

from hogli.migration_utils import (
    MIGRATION_CACHE_DIR,
    get_cached_migration,
    get_managed_app_names,
    hidden_conflicting_migrations,
    is_valid_migration_path,
    temporary_max_migration,
    temporary_migration_file,
)


def get_managed_apps() -> set[str]:
    """Get apps we manage migrations for (PostHog apps, not third-party)."""
    try:
        return get_managed_app_names(Path(settings.BASE_DIR))
    except Exception as e:
        warnings.warn(f"Could not scan product apps for migrations: {e}", stacklevel=2)
        return {"posthog", "ee", "rbac"}


def get_app_migrations_dir(app_label: str) -> Path | None:
    """Get the migrations directory for an app."""
    try:
        from django.apps import apps

        app_config = apps.get_app_config(app_label)
        return Path(app_config.path) / "migrations"
    except LookupError:
        return None


def cache_migration(app_label: str, migration_name: str) -> bool:
    """Cache a migration file for later rollback.

    Validates inputs to prevent path traversal attacks.
    """
    # Validate inputs to prevent path traversal
    if not is_valid_migration_path(app_label, migration_name):
        return False

    migrations_dir = get_app_migrations_dir(app_label)
    if not migrations_dir:
        return False

    source_path = migrations_dir / f"{migration_name}.py"
    if not source_path.exists():
        return False

    cache_path = MIGRATION_CACHE_DIR / app_label / f"{migration_name}.py"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copy2(source_path, cache_path)
        return True
    except Exception as e:
        warnings.warn(f"Could not cache migration {app_label}.{migration_name}: {e}", stacklevel=2)
        return False


def get_orphaned_migrations(connection) -> list[tuple[str, str]]:
    """Find migrations applied in DB but not present in code.

    Returns list of (app_label, migration_name) tuples.
    """
    from django.db.migrations.loader import MigrationLoader

    loader = MigrationLoader(connection, ignore_no_migrations=True)
    recorder = MigrationRecorder(connection)
    applied = recorder.applied_migrations()
    managed_apps = get_managed_apps()

    orphaned = []
    for app_label, migration_name in applied:
        # Only check apps we manage
        if app_label not in managed_apps:
            continue

        # Check if migration exists in the loader's disk migrations
        if (app_label, migration_name) not in loader.disk_migrations:
            orphaned.append((app_label, migration_name))

    return orphaned


def get_previous_migration(app_label: str, migration_name: str, connection) -> str:
    """Get the migration to roll back to (the one before the given migration)."""
    from django.db.migrations.loader import MigrationLoader

    loader = MigrationLoader(connection, ignore_no_migrations=True)
    recorder = MigrationRecorder(connection)
    applied = recorder.applied_migrations()

    # Get all applied migrations for this app, sorted
    app_migrations = sorted([name for app, name in applied if app == app_label])

    if not app_migrations:
        return "zero"

    try:
        idx = app_migrations.index(migration_name)
        if idx == 0:
            return "zero"
        return app_migrations[idx - 1]
    except ValueError:
        # Migration not in list, check disk migrations
        disk_migrations = sorted([name for app, name in loader.disk_migrations if app == app_label])
        return disk_migrations[-1] if disk_migrations else "zero"


def rollback_orphaned_migration(app_label: str, migration_name: str, previous: str, stdout) -> bool:
    """Roll back a single orphaned migration using its cached file.

    Uses context managers to ensure proper cleanup of temporary files,
    hidden migrations, and max_migration.txt regardless of success or failure.

    Returns True on success, False on failure.
    """
    cache_path = get_cached_migration(app_label, migration_name)
    if not cache_path:
        return False

    migrations_dir = get_app_migrations_dir(app_label)
    if not migrations_dir:
        return False

    target_path = migrations_dir / f"{migration_name}.py"

    try:
        with (
            hidden_conflicting_migrations(migrations_dir, migration_name),
            temporary_migration_file(cache_path, target_path),
            temporary_max_migration(migrations_dir, migration_name),
        ):
            result = subprocess.run(
                [
                    sys.executable,
                    "manage.py",
                    "migrate",
                    app_label,
                    previous,
                    "--no-input",
                    "--skip-orphan-check",
                    "--skip-checks",
                ],
                cwd=settings.BASE_DIR,
                env={**os.environ, "DJANGO_SETTINGS_MODULE": "posthog.settings"},
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                stdout.write(f"    Error: {result.stderr.strip()}")
                return False

            return True
    except Exception as e:
        # Log with traceback so cleanup failures don't mask the original error
        warnings.warn(f"Rollback failed for {app_label}.{migration_name}: {e}", stacklevel=2)
        stdout.write(f"    Error: {e}")
        return False


class Command(DjangoMigrateCommand):
    """Extended migrate command with caching and orphan detection."""

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--skip-orphan-check",
            action="store_true",
            help="Skip checking for orphaned migrations before migrating.",
        )

    def handle(self, *args, **options):
        database = options.get("database", DEFAULT_DB_ALIAS)
        interactive = options.get("interactive", True)
        skip_orphan_check = options.get("skip_orphan_check", False)

        # Get connection for orphan check
        from django.db import connections

        connection = connections[database]

        # Check for orphaned migrations before proceeding
        if not skip_orphan_check and not options.get("check_unapplied"):
            try:
                orphaned = get_orphaned_migrations(connection)
                if orphaned:
                    self.stdout.write("")
                    self.stdout.write(self.style.WARNING("⚠️  Orphaned migrations detected!"))
                    self.stdout.write("These migrations are applied in the DB but don't exist in code.")
                    self.stdout.write("They were likely applied on another branch.\n")

                    # Categorize by whether we can auto-fix
                    cached_orphans = []
                    uncached_orphans = []
                    for app_label, migration_name in orphaned:
                        cached = get_cached_migration(app_label, migration_name)
                        if cached:
                            cached_orphans.append((app_label, migration_name))
                        else:
                            uncached_orphans.append((app_label, migration_name))
                        status = "cached" if cached else "not cached"
                        self.stdout.write(f"    {app_label}: {migration_name} ({status})")

                    self.stdout.write("")

                    if interactive:
                        # Offer to fix if all orphans are cached
                        if cached_orphans and not uncached_orphans:
                            self.stdout.write("All orphaned migrations are cached and can be rolled back.\n")
                            choice = input("Roll back now and continue? [Y/n/abort] ").strip().lower()

                            if choice in ("", "y", "yes"):
                                self.stdout.write("")
                                self.stdout.write(self.style.MIGRATE_HEADING("Rolling back orphaned migrations…"))

                                for app_label, migration_name in cached_orphans:
                                    previous = get_previous_migration(app_label, migration_name, connection)
                                    self.stdout.write(f"  Rolling back {app_label}.{migration_name}…")

                                    if rollback_orphaned_migration(app_label, migration_name, previous, self.stdout):
                                        self.stdout.write(
                                            self.style.SUCCESS(f"  ✓ Rolled back {app_label}.{migration_name}")
                                        )
                                    else:
                                        self.stdout.write(
                                            self.style.ERROR(f"  ✗ Failed to roll back {app_label}.{migration_name}")
                                        )
                                        self.stdout.write("Aborted.")
                                        return

                                self.stdout.write("")
                            elif choice in ("n", "no"):
                                # Continue without rolling back
                                self.stdout.write("Continuing without rolling back…\n")
                            else:
                                self.stdout.write("Aborted.")
                                return
                        else:
                            # Some uncached - can't auto-fix all
                            if uncached_orphans:
                                self.stdout.write(
                                    self.style.WARNING(
                                        "Some migrations are not cached and cannot be auto-rolled back.\n"
                                        "Run 'hogli migrations:sync' for manual instructions.\n"
                                    )
                                )
                            confirm = input("Continue anyway? [y/N] ")
                            if confirm.lower() not in ("y", "yes"):
                                self.stdout.write("Aborted.")
                                return
                    else:
                        # Non-interactive mode: warn but continue
                        self.stdout.write(
                            self.style.WARNING(
                                "Continuing in non-interactive mode. Run 'hogli migrations:sync' after to clean up."
                            )
                        )
            except Exception as e:
                # Don't block migrations if orphan check fails
                self.stdout.write(self.style.WARNING(f"⚠️  Could not check for orphaned migrations: {e}"))

        # Get migrations that will be applied (before running migrate)
        recorder = MigrationRecorder(connection)
        applied_before = set(recorder.applied_migrations())

        # Run the actual migrate command
        super().handle(*args, **options)

        # Cache any newly applied migrations
        applied_after = set(recorder.applied_migrations())
        newly_applied = applied_after - applied_before
        managed_apps = get_managed_apps()

        for app_label, migration_name in newly_applied:
            if app_label in managed_apps:
                if cache_migration(app_label, migration_name):
                    self.stdout.write(self.style.SUCCESS(f"  Cached: {app_label}.{migration_name}"))

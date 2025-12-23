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

# Cache directory for migration files
MIGRATION_CACHE_DIR = Path.home() / ".cache" / "posthog-migrations"


def get_managed_apps() -> set[str]:
    """Get apps we manage migrations for (PostHog apps, not third-party)."""
    managed = {"posthog", "ee", "rbac"}

    # Also include product apps from products/*/backend/
    try:
        products_dir = Path(settings.BASE_DIR) / "products"
        if products_dir.exists():
            for product_dir in products_dir.iterdir():
                if product_dir.is_dir():
                    migrations_dir = product_dir / "backend" / "migrations"
                    if migrations_dir.exists():
                        managed.add(product_dir.name)
    except Exception as e:
        warnings.warn(f"Could not scan product apps for migrations: {e}", stacklevel=2)

    return managed


def get_app_migrations_dir(app_label: str) -> Path | None:
    """Get the migrations directory for an app."""
    try:
        from django.apps import apps

        app_config = apps.get_app_config(app_label)
        return Path(app_config.path) / "migrations"
    except LookupError:
        return None


def cache_migration(app_label: str, migration_name: str) -> bool:
    """Cache a migration file for later rollback."""
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


def get_cached_migration(app_label: str, migration_name: str) -> Path | None:
    """Check if a migration is cached."""
    cache_path = MIGRATION_CACHE_DIR / app_label / f"{migration_name}.py"
    return cache_path if cache_path.exists() else None


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

    Handles the case where there are conflicting migrations (same number prefix)
    by temporarily hiding them during the rollback.

    Returns True on success, False on failure.
    """
    cache_path = get_cached_migration(app_label, migration_name)
    if not cache_path:
        return False

    migrations_dir = get_app_migrations_dir(app_label)
    if not migrations_dir:
        return False

    target_path = migrations_dir / f"{migration_name}.py"

    # Handle max_migration.txt for PostHog's migration check
    max_migration_path = migrations_dir / "max_migration.txt"
    original_max_migration = None

    # Find conflicting migrations (same number prefix, different name)
    # e.g., 0952_add_migration_test_field conflicts with 0952_add_sync_test_branch_two
    migration_prefix = migration_name.split("_")[0]  # e.g., "0952"
    hidden_migrations: list[tuple[Path, Path]] = []  # (original, hidden) pairs

    try:
        # Find and temporarily hide conflicting migrations
        for migration_file in migrations_dir.glob(f"{migration_prefix}_*.py"):
            if migration_file.name != f"{migration_name}.py":
                hidden_path = migration_file.with_suffix(".py.hidden")
                migration_file.rename(hidden_path)
                hidden_migrations.append((migration_file, hidden_path))

        # Copy cached file to migrations directory temporarily
        shutil.copy2(cache_path, target_path)

        # Temporarily update max_migration.txt if it exists
        if max_migration_path.exists():
            original_max_migration = max_migration_path.read_text().strip()
            max_migration_path.write_text(f"{migration_name}\n")

        # Run Django migrate to roll back
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

        # Clean up the temporary file
        target_path.unlink(missing_ok=True)

        # Restore max_migration.txt
        if original_max_migration is not None:
            max_migration_path.write_text(f"{original_max_migration}\n")

        # Restore hidden migrations
        for original, hidden in hidden_migrations:
            hidden.rename(original)

        if result.returncode != 0:
            stdout.write(f"    Error: {result.stderr.strip()}")
            return False

        return True

    except Exception as e:
        # Clean up on failure - wrap each cleanup in try/except to ensure all run
        try:
            target_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            if original_max_migration is not None:
                max_migration_path.write_text(f"{original_max_migration}\n")
        except Exception:
            pass
        # Restore hidden migrations
        for original, hidden in hidden_migrations:
            try:
                if hidden.exists():
                    hidden.rename(original)
            except Exception:
                pass
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

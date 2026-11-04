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
import json
import time
import shutil
import warnings
import subprocess
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.management.commands.migrate import Command as DjangoMigrateCommand
from django.db import DEFAULT_DB_ALIAS, NotSupportedError
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder

from posthog.cloud_utils import is_ci
from posthog.management.migration_profiling.profiler import profile_migrations

from common.migration_utils import (
    MIGRATION_CACHE_DIR,
    get_cached_migration,
    get_managed_app_names,
    hidden_conflicting_migrations,
    is_valid_migration_path,
    temporary_max_migration,
    temporary_migration_file,
)

if TYPE_CHECKING:
    from django.db.backends.base.base import BaseDatabaseWrapper


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


# EX_CONFIG from sysexits.h. bin/migrate reads it to skip its retries.
UNSUPPORTED_DATABASE_EXIT_CODE = 78


def check_database_version(connection: BaseDatabaseWrapper) -> None:
    """Stop with recovery steps when the server is older than Django supports.

    Django refuses to connect below its minimum version, so without this the run
    dies on its first query with a raw driver error and no way forward.
    """
    try:
        connection.ensure_connection()
    except NotSupportedError as exc:
        raise CommandError(
            f"{exc}\n\n"
            "No migration ran, so the database is unchanged. Upgrade the PostgreSQL "
            "server to a supported version, then deploy again.\n\n"
            "On a Docker Compose deployment:\n"
            "  1. Back up the data. Stop here if this reports an error:\n"
            "     docker compose exec -T db pg_dumpall --clean -U posthog > posthog-backup.sql && gzip -f posthog-backup.sql\n"
            "  2. Check that the backup is complete. The last lines must say the cluster dump is complete:\n"
            "     gunzip -c posthog-backup.sql.gz | tail -3\n"
            "  3. Stop the stack, then delete the old postgres-data volume. The backup file is now the only copy of the data.\n"
            "  4. Start the db service again. It uses the PostgreSQL version PostHog pins.\n"
            "  5. Restore the data. Errors about the posthog role and database already existing are expected:\n"
            "     gunzip -c posthog-backup.sql.gz | docker compose exec -T db psql -U posthog\n"
            "  6. Check that the data is back. This must print a count, not an error:\n"
            "     docker compose exec -T db psql -U posthog -c 'select count(*) from django_migrations'",
            returncode=UNSUPPORTED_DATABASE_EXIT_CODE,
        ) from exc


# The last master commit before the newest squash. Its migration files are the ones the
# squash replaced, before the squash tool removed any dependency entries from them, so a
# database of any age migrates there in the original order. Move it with each new squash.
MIGRATION_FLOOR_COMMIT = "c985c0dd7a7efeecfc9ef838e09303382261a23e"

MigrationKey = tuple[str, str]


def load_removed_dependencies() -> list[MigrationKey]:
    """Return the migrations that run without a dependency entry the squash tool removed.

    The squash tool removes cross-app entries from replaced files to break dependency
    cycles between squashes. For a `dependencies` entry the edited file is the side
    that lost its prerequisite. For a `run_before` entry the target is.
    """
    path = Path(settings.BASE_DIR) / str(settings.NEXTGENSQUASH["REMOVED_DEPENDENCIES_FILE"])
    dependents = set()
    for removed in json.loads(path.read_text())["removed"]:
        side = removed["file"] if removed["attribute"] == "dependencies" else removed["entry"]
        dependents.add((side[0], side[1]))
    return sorted(dependents)


def resolve_replaced(
    replaces: Mapping[MigrationKey, Collection[MigrationKey]],
) -> dict[MigrationKey, set[MigrationKey]]:
    """Map each squash to the migration names it stands for, at any depth of nesting.

    A database records these names when it runs the original files, so they decide
    whether Django applies the squash or falls back to the files it replaces.
    """

    def originals(key: MigrationKey) -> set[MigrationKey]:
        if key not in replaces:
            return {key}
        return {original for replaced in replaces[key] for original in originals(replaced)}

    return {key: originals(key) for key in replaces}


def find_unsafe_fallback(
    replaced: Mapping[MigrationKey, set[MigrationKey]],
    dependents: Collection[MigrationKey],
    applied: Collection[MigrationKey],
    target: MigrationKey | None = None,
) -> list[str]:
    """Return the migrations that lost a dependency entry and would run on this database.

    Django runs a squash's replaced files instead of the squash when the database applied
    some of them but not all. A file that lost a dependency entry then runs without that
    ordering, so a run can fail half way. An applied file does not run again. A target that
    names a replaced migration makes Django ignore every squash, so every such file runs.
    """
    targets_replaced = target is not None and any(target in members for members in replaced.values())
    unsafe = []
    for dependent in dependents:
        if dependent in applied:
            continue
        if targets_replaced:
            unsafe.append(f"{dependent[0]}.{dependent[1]}")
            continue
        containing = [members for members in replaced.values() if dependent in members]
        if not containing:
            continue
        innermost = min(containing, key=len)
        if any(member in applied for member in innermost):
            unsafe.append(f"{dependent[0]}.{dependent[1]}")
    return sorted(unsafe)


def resolve_target(
    disk: Collection[MigrationKey], app_label: str | None, migration_name: str | None
) -> MigrationKey | None:
    """Return the migration a `migrate <app> <name>` call targets, the way Django matches a prefix."""
    if not app_label or not migration_name or migration_name == "zero":
        return None
    matches = [key for key in disk if key[0] == app_label and key[1].startswith(migration_name)]
    exact = (app_label, migration_name)
    if exact in matches:
        return exact
    return matches[0] if len(matches) == 1 else None


def check_migration_history_is_supported(
    connection: BaseDatabaseWrapper, app_label: str | None, migration_name: str | None
) -> None:
    """Stop with upgrade steps when this migrate would run files the squash tool edited.

    Reads the migration files without building the graph, because a graph that cannot be
    ordered raises before any message could explain it. A target that names a replaced
    migration makes Django ignore every squash, so each edited file that is not applied runs.
    """
    loader = MigrationLoader(connection, load=False, ignore_no_migrations=True)
    loader.load_disk()
    replaces = {
        key: [(app_label, name) for app_label, name in migration.replaces]
        for key, migration in loader.disk_migrations.items()
        if migration.replaces
    }
    replaced = resolve_replaced(replaces)
    dependents = load_removed_dependencies()
    applied = set(MigrationRecorder(connection).applied_migrations())
    target = resolve_target(loader.disk_migrations, app_label, migration_name)
    unsafe = find_unsafe_fallback(replaced, dependents, applied, target)
    if not unsafe:
        return
    raise CommandError(
        "This database stopped migrating before the oldest history this release supports. "
        f"These migrations would run without the order they need: {', '.join(unsafe)}.\n\n"
        "No migration ran, so the database is unchanged. Upgrade in two steps:\n"
        f"  1. Run migrations on PostHog at commit {MIGRATION_FLOOR_COMMIT}.\n"
        f"     In a dev checkout: git checkout {MIGRATION_FLOOR_COMMIT} && ./bin/migrate\n"
        f"     On a Docker Compose deployment: set POSTHOG_APP_TAG={MIGRATION_FLOOR_COMMIT} and deploy.\n"
        "  2. Return to this release and migrate again.\n\n"
        "A local dev database can start over instead: hogli dev:reset deletes its data.",
        returncode=UNSUPPORTED_DATABASE_EXIT_CODE,
    )


class Command(DjangoMigrateCommand):
    """Extended migrate command with caching and orphan detection."""

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--skip-orphan-check",
            action="store_true",
            help="Skip checking for orphaned migrations before migrating.",
        )
        parser.add_argument(
            "--production",
            action="store_true",
            help="Production mode: skip orphan check and migration caching (local-dev features).",
        )
        parser.add_argument(
            "--profile-operations",
            action="store_true",
            help="Capture per-operation and per-SQL-statement timings into a JSONL file.",
        )
        parser.add_argument(
            "--profile-output",
            metavar="PATH",
            default=None,
            help="Path to write the profile JSONL. Defaults to /tmp/migration-profile-<db>-<unix_ts>.jsonl.",
        )
        parser.add_argument(
            "--profile-full-sql",
            action="store_true",
            help="Don't truncate captured SQL bodies (default truncates at 4 KB).",
        )

    def handle(self, *args, **options):
        database = options.get("database", DEFAULT_DB_ALIAS)
        interactive = options.get("interactive", True)
        production_mode = options.get("production", False)
        test_mode = settings.TEST
        profile_operations = options.get("profile_operations", False)
        # When profiling, the assumption is a fresh-DB run — both code paths
        # below assume migrations were previously applied, which fights that.
        # The cache and the orphan check serve local worktree switches, not CI.
        skip_caching = production_mode or test_mode or profile_operations or is_ci()
        skip_orphan_check = options.get("skip_orphan_check", False) or skip_caching

        # Get connection for orphan check
        from django.db import connections

        connection = connections[database]

        check_database_version(connection)
        # A fake run records history without running operations, so the removed ordering cannot break it.
        if not options.get("fake"):
            check_migration_history_is_supported(connection, options.get("app_label"), options.get("migration_name"))

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

                                # Sort in reverse order so dependent migrations are rolled back first
                                # (e.g., 0004 must be rolled back before 0003)
                                cached_orphans.sort(key=lambda x: x[1], reverse=True)
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

        # Track applied migrations for caching (skip in production and test mode)
        if not skip_caching:
            recorder = MigrationRecorder(connection)
            applied_before = set(recorder.applied_migrations())

        # Run the actual migrate command — optionally under the profiler.
        if profile_operations:
            profile_output = options.get("profile_output")
            if not profile_output:
                profile_output = f"/tmp/migration-profile-{database}-{int(time.time())}.jsonl"
            profile_path = Path(profile_output)
            full_sql = options.get("profile_full_sql", False)

            # Optional Python-side sampling via pyinstrument. Pure Python, no
            # root needed (unlike py-spy on macOS). Activated automatically if
            # pyinstrument is importable.
            py_profiler = None
            html_path = profile_path.with_suffix(".pyinstrument.html")
            try:
                from pyinstrument import Profiler

                py_profiler = Profiler(interval=0.01)
                py_profiler.start()
            except ImportError:
                pass

            try:
                with profile_migrations(database=database, output_path=profile_path, full_sql=full_sql):
                    super().handle(*args, **options)
            finally:
                if py_profiler is not None:
                    py_profiler.stop()
                    try:
                        html_path.write_text(py_profiler.output_html())
                        self.stdout.write(self.style.SUCCESS(f"Wrote pyinstrument HTML to {html_path}"))
                    except Exception as exc:
                        self.stdout.write(self.style.WARNING(f"pyinstrument HTML failed: {exc}"))
                    try:
                        from pyinstrument.renderers import JSONRenderer

                        json_path = profile_path.with_suffix(".pyinstrument.json")
                        json_path.write_text(py_profiler.output(JSONRenderer()))
                        self.stdout.write(self.style.SUCCESS(f"Wrote pyinstrument JSON to {json_path}"))
                    except Exception as exc:
                        self.stdout.write(self.style.WARNING(f"pyinstrument JSON failed: {exc}"))
                    try:
                        from pyinstrument.renderers import SpeedscopeRenderer

                        speedscope_path = profile_path.with_suffix(".speedscope.json")
                        speedscope_path.write_text(py_profiler.output(SpeedscopeRenderer()))
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Wrote speedscope JSON to {speedscope_path} — open at https://www.speedscope.app/"
                            )
                        )
                    except Exception as exc:
                        self.stdout.write(self.style.WARNING(f"pyinstrument speedscope failed: {exc}"))

            self.stdout.write(self.style.SUCCESS(f"Wrote migration profile to {profile_path}"))
        else:
            super().handle(*args, **options)

        # Cache any newly applied migrations (skip in production and test mode)
        if not skip_caching:
            applied_after = set(recorder.applied_migrations())
            newly_applied = applied_after - applied_before
            managed_apps = get_managed_apps()

            for app_label, migration_name in newly_applied:
                if app_label in managed_apps:
                    if cache_migration(app_label, migration_name):
                        self.stdout.write(self.style.SUCCESS(f"  Cached: {app_label}.{migration_name}"))

        # A fresh database takes the squash path, which folds the historical
        # RunPython seeds (auth groups, default theme, dashboard templates,
        # ...). Re-seed after every default-DB migrate; the command is
        # idempotent and a no-op on databases that already carry the rows.
        # Skipped when targeting another alias or checking, never on failure —
        # a migrate that raised has already propagated by this point.
        if database == DEFAULT_DB_ALIAS and not options.get("check_unapplied") and not options.get("plan"):
            try:
                call_command("ensure_migration_defaults", verbosity=0)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"ensure_migration_defaults failed: {exc}"))

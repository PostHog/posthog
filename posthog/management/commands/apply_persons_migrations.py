"""Apply persons SQL migrations.

Reads SQL migration files from rust/persons_migrations/ and executes them against the
persons database identified by PERSONS_DB_WRITER_URL. Hobby deploys keep persons in the
main database and skip the partitioning migrations (via --hobby); local dev and
production apply all migrations.

Tracks applied migrations in a _persons_migrations_applied table so each
migration is only executed once. Also bridges the sqlx _sqlx_migrations
tracking table so that environments transitioning from sqlx don't re-apply
already-applied migrations.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from posthog.persons_db import persons_db_connection, persons_db_url

# Migrations that must be skipped on hobby deploys.
# These partition the posthog_person table, which is only needed in production
# where the table is large enough to benefit from hash partitioning.
HOBBY_SKIP_MIGRATIONS = {
    "20251113000001_add_partitioned_person_table.sql",
    "20251115000001_add_partition_indexes_and_foreign_keys.sql",
    "20251117000001_rename_person_tables.sql",
}

TRACKING_TABLE = "_persons_migrations_applied"

# Serializes concurrent runners (e.g. multiple instances during a deploy) so that only one
# applies migrations at a time. Without it, runners read a stale snapshot of applied migrations
# and collide on both the initial-schema DDL and the tracking-table INSERT.
ADVISORY_LOCK_KEY = "posthog_apply_persons_migrations"


def _ensure_tracking_table(cursor) -> None:
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {TRACKING_TABLE} (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)


def _get_applied_migrations(cursor) -> set[str]:
    cursor.execute(f"SELECT filename FROM {TRACKING_TABLE}")
    return {row[0] for row in cursor.fetchall()}


def _get_sqlx_applied_versions(cursor) -> set[str]:
    """Return version strings from the sqlx _sqlx_migrations table, if it exists.

    sqlx stores versions as bigints matching the filename prefix (e.g. 20250923000001)
    and descriptions as space-separated words (e.g. 'initial persons schema').
    We return version strings so callers can match against filename prefixes.
    """
    cursor.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = '_sqlx_migrations'
        )
    """)
    if not cursor.fetchone()[0]:
        return set()

    cursor.execute("SELECT version FROM _sqlx_migrations WHERE success = true")
    return {str(row[0]) for row in cursor.fetchall()}


def _record_migration(cursor, filename: str) -> None:
    cursor.execute(
        f"INSERT INTO {TRACKING_TABLE} (filename) VALUES (%s) ON CONFLICT (filename) DO NOTHING",
        [filename],
    )


def _acquire_advisory_lock(cursor) -> None:
    cursor.execute("SELECT pg_advisory_lock(hashtext(%s)::bigint)", [ADVISORY_LOCK_KEY])


def _release_advisory_lock(cursor) -> None:
    cursor.execute("SELECT pg_advisory_unlock(hashtext(%s)::bigint)", [ADVISORY_LOCK_KEY])


def _ensure_database_exists(persons_url: str) -> None:
    """Create the persons database named in ``persons_url`` if it doesn't already exist.

    Connects to the 'postgres' maintenance database on the same host (reusing the
    credentials from the URL, only overriding the database name) and issues CREATE
    DATABASE. Used for local dev bootstrap.
    """
    params = conninfo_to_dict(persons_url)
    dbname = params.get("dbname")
    if not dbname:
        raise RuntimeError("Persons database URL has no database name; cannot ensure it exists.")
    # conninfo_to_dict types values as ``str | int``; identifiers must be ``str``.
    target_db = str(dbname)

    try:
        with psycopg.connect(persons_url, dbname="postgres", autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
                if cur.fetchone():
                    return

                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
                owner = params.get("user")
                if owner:
                    cur.execute(
                        sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
                            sql.Identifier(target_db),
                            sql.Identifier(str(owner)),
                        )
                    )
    except psycopg.OperationalError as exc:
        raise RuntimeError(
            f"Unable to ensure persons database '{target_db}' exists. Is Postgres running and accessible?"
        ) from exc


class Command(BaseCommand):
    help = "Apply persons SQL migrations (reads from rust/persons_migrations/)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--migrations-dir",
            type=str,
            default=None,
            help="Path to the persons migrations directory. Defaults to rust/persons_migrations/ relative to BASE_DIR.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print which migrations would be applied without executing them.",
        )
        parser.add_argument(
            "--hobby",
            action="store_true",
            help="Skip partitioning migrations (for hobby deploys where posthog_person is not partitioned).",
        )
        parser.add_argument(
            "--ensure-database",
            action="store_true",
            help="Create the target database if it doesn't exist (for local dev bootstrap).",
        )

    def handle(self, *args, **options):
        hobby = options["hobby"]
        dry_run = options["dry_run"]
        persons_url = persons_db_url(writer=True)

        if options["ensure_database"] and not dry_run:
            _ensure_database_exists(persons_url)

        migrations_path = self._resolve_migrations_dir(options["migrations_dir"])
        sql_files = sorted(f for f in migrations_path.iterdir() if f.suffix == ".sql")
        if not sql_files:
            self.stdout.write("No SQL migration files found.")
            return

        applied_count = 0
        skipped_count = 0
        already_applied_count = 0

        with persons_db_connection(writer=True, autocommit=True) as conn, conn.cursor() as cursor:
            # Hold a session-level advisory lock across the whole loop so concurrent runners
            # apply migrations one at a time instead of racing on the schema DDL and tracking rows.
            if not dry_run:
                _acquire_advisory_lock(cursor)
            try:
                if not dry_run:
                    _ensure_tracking_table(cursor)
                # Read applied migrations only after taking the lock, so we see any rows a prior
                # runner committed while we were waiting rather than a stale startup snapshot.
                already_applied = _get_applied_migrations(cursor) if not dry_run else set()

                # Bridge sqlx tracking: migrations already applied by sqlx should
                # not be re-applied. sqlx stores the version prefix as a bigint.
                sqlx_versions = _get_sqlx_applied_versions(cursor) if not dry_run else set()

                for sql_file in sql_files:
                    if hobby and sql_file.name in HOBBY_SKIP_MIGRATIONS:
                        self.stdout.write(f"  Skipping {sql_file.name} (partitioning)")
                        skipped_count += 1
                        continue

                    if sql_file.name in already_applied:
                        already_applied_count += 1
                        continue

                    # Extract version prefix (e.g. "20250923000001" from "20250923000001_initial_persons_schema.sql")
                    version_prefix = sql_file.stem.split("_", 1)[0]
                    if version_prefix in sqlx_versions:
                        # sqlx already ran this migration; record it in our tracking table
                        if not dry_run:
                            _record_migration(cursor, sql_file.name)
                        self.stdout.write(f"  Bridged from sqlx: {sql_file.name}")
                        already_applied_count += 1
                        continue

                    if dry_run:
                        self.stdout.write(f"  Would apply: {sql_file.name}")
                        applied_count += 1
                        continue

                    sql_content = sql_file.read_text()
                    self.stdout.write(f"  Applying {sql_file.name}...")
                    with conn.transaction():
                        cursor.execute(sql_content)
                        _record_migration(cursor, sql_file.name)
                    applied_count += 1
            finally:
                if not dry_run:
                    _release_advisory_lock(cursor)

        action = "Would apply" if dry_run else "Applied"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {applied_count} migration(s), skipped {skipped_count}, "
                f"already applied {already_applied_count}."
            )
        )

    def _resolve_migrations_dir(self, override: str | None) -> Path:
        if override:
            path = Path(override)
        else:
            path = Path(settings.BASE_DIR) / "rust" / "persons_migrations"

        if not path.is_dir():
            raise CommandError(f"Migrations directory not found: {path}")
        return path

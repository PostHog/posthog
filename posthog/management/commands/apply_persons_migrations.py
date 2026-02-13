"""Apply persons SQL migrations for hobby deploys.

Reads SQL migration files from rust/persons_migrations/ and executes them
against the default database, skipping partitioning migrations that are only
needed in production.

Tracks applied migrations in a _persons_migrations_applied table so each
migration is only executed once, regardless of whether the SQL is idempotent.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

# Migrations that must be skipped on hobby deploys.
# These partition the posthog_person table, which is only needed in production
# where the table is large enough to benefit from hash partitioning.
SKIP_MIGRATIONS = {
    "20251113000001_add_partitioned_person_table.sql",
    "20251115000001_add_partition_indexes_and_foreign_keys.sql",
    "20251117000001_rename_person_tables.sql",
}

TRACKING_TABLE = "_persons_migrations_applied"


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


def _record_migration(cursor, filename: str) -> None:
    cursor.execute(f"INSERT INTO {TRACKING_TABLE} (filename) VALUES (%s)", [filename])


class Command(BaseCommand):
    help = "Apply persons SQL migrations for hobby deploys (reads from rust/persons_migrations/)"

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

    def handle(self, *args, **options):
        migrations_path = self._resolve_migrations_dir(options["migrations_dir"])
        sql_files = sorted(f for f in migrations_path.iterdir() if f.suffix == ".sql")
        if not sql_files:
            self.stdout.write("No SQL migration files found.")
            return

        dry_run = options["dry_run"]
        applied_count = 0
        skipped_count = 0
        already_applied_count = 0

        with connection.cursor() as cursor:
            if not dry_run:
                _ensure_tracking_table(cursor)
            already_applied = _get_applied_migrations(cursor) if not dry_run else set()

            for sql_file in sql_files:
                if sql_file.name in SKIP_MIGRATIONS:
                    self.stdout.write(f"  Skipping {sql_file.name} (partitioning)")
                    skipped_count += 1
                    continue

                if sql_file.name in already_applied:
                    already_applied_count += 1
                    continue

                if dry_run:
                    self.stdout.write(f"  Would apply: {sql_file.name}")
                    applied_count += 1
                    continue

                sql = sql_file.read_text()
                self.stdout.write(f"  Applying {sql_file.name}...")
                with transaction.atomic():
                    # psycopg2 handles multi-statement SQL strings natively.
                    # Do NOT split on ';' — DO $$ blocks contain internal semicolons.
                    cursor.execute(sql)
                    _record_migration(cursor, sql_file.name)
                applied_count += 1

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

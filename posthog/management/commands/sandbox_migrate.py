"""Run all database migrations in a single Django process.

Combines migrate, apply_persons_migrations, and migrate_clickhouse into one
command to avoid three separate Django cold starts (~15s each). Used by the
sandbox entrypoint to speed up boot time.

Migrations run sequentially because ClickHouse migrations call
get_instance_setting() which queries the Django posthog_instancesetting table,
so ClickHouse must run after Django.
"""

import time
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run all migrations (Django, persons, ClickHouse) in one process"

    def add_arguments(self, parser):
        parser.add_argument("--progress-file", type=str, help="File to write progress updates to")

    def _progress(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S", time.gmtime())
        self.stdout.write(f"[{ts}] {msg}")
        if self._progress_file:
            with open(self._progress_file, "a") as f:
                f.write(f"[{ts}] ==> {msg}\n")

    def handle(self, *args, **options):
        self._progress_file: Path | None = Path(options["progress_file"]) if options.get("progress_file") else None

        tasks = [
            (
                "Django + product DBs",
                lambda: (call_command("migrate", "--noinput"), call_command("migrate_product_databases")),
            ),
            (
                "persons",
                lambda: call_command("apply_persons_migrations", "--database=persons_db_writer", "--ensure-database"),
            ),
            ("ClickHouse", lambda: call_command("migrate_clickhouse")),
        ]

        for name, fn in tasks:
            self._progress(f"Starting {name} migrations...")
            fn()
            self._progress(f"Finished {name} migrations.")

        self._progress("All migrations complete.")

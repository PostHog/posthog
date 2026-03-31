"""Run all database migrations in a single Django process.

Combines migrate, apply_persons_migrations, and migrate_clickhouse into one
command to avoid three separate Django cold starts (~15s each). Used by the
sandbox entrypoint to speed up boot time.

With --parallel, all three run concurrently (used during cache-init when
migrations are slow and Django is already loaded). Without it, they run
in series (used on branch sandboxes where migrations are incremental and
fast relative to Django startup).
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run all migrations (Django, persons, ClickHouse) in one process"

    def add_arguments(self, parser):
        parser.add_argument("--parallel", action="store_true", help="Run all three migration targets concurrently")
        parser.add_argument("--progress-file", type=str, help="File to write progress updates to")

    def _progress(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S", time.gmtime())
        self.stdout.write(f"[{ts}] {msg}")
        if self._progress_file:
            with open(self._progress_file, "a") as f:
                f.write(f"[{ts}] ==> {msg}\n")

    def handle(self, *args, **options):
        self._progress_file: Path | None = Path(options["progress_file"]) if options.get("progress_file") else None

        tasks = {
            "Django": lambda: call_command("migrate", "--noinput"),
            "persons": lambda: call_command(
                "apply_persons_migrations", "--database=persons_db_writer", "--ensure-database"
            ),
            "ClickHouse": lambda: call_command("migrate_clickhouse"),
        }

        if options["parallel"]:

            def run_task(name: str, fn):
                self._progress(f"Starting {name} migrations...")
                fn()
                self._progress(f"Finished {name} migrations.")

            with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
                futures = {pool.submit(run_task, name, fn): name for name, fn in tasks.items()}
                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        self.stderr.write(
                            self.style.ERROR(
                                f"[{time.strftime('%H:%M:%S', time.gmtime())}] {name} migrations failed: {e}"
                            )
                        )
                        raise
        else:
            for name, fn in tasks.items():
                self.stdout.write(f"[{time.strftime('%H:%M:%S', time.gmtime())}] Running {name} migrations...")
                fn()

        self._progress("All migrations complete.")

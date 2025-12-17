import csv
from collections.abc import Iterator

from django.core.management.base import BaseCommand, CommandError

from clickhouse_driver.errors import SocketTimeoutError

from posthog.clickhouse.client import sync_execute
from posthog.models.team.team import Team
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER

BATCH_SIZE = 1000


class Command(BaseCommand):
    help = "Delete session replay events from ClickHouse by session_id"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", required=True, type=int, help="Team ID for the session recordings")
        parser.add_argument("--session-ids", type=str, help="Comma-separated list of session IDs")
        parser.add_argument("--csv-file", type=str, help="Path to CSV file with session IDs (single column)")
        parser.add_argument("--skip-header", action="store_true", help="Skip the first row of the CSV file")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
        parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help=f"Batch size (default: {BATCH_SIZE})")

    def handle(self, *args, **options):
        team_id = options["team_id"]
        session_ids_arg = options["session_ids"]
        csv_file = options["csv_file"]
        skip_header = options["skip_header"]
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        if not session_ids_arg and not csv_file:
            raise CommandError("Must provide either --session-ids or --csv-file")

        if session_ids_arg and csv_file:
            raise CommandError("Provide only one of --session-ids or --csv-file, not both")

        team = Team.objects.filter(id=team_id).first()
        if not team:
            raise CommandError(f"Team with ID {team_id} does not exist")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run - no changes will be made"))
            self._process_dry_run(team, session_ids_arg, csv_file, skip_header, batch_size)
        else:
            self._process_deletions(team, session_ids_arg, csv_file, skip_header, batch_size)

    def _iter_session_ids(self, session_ids_arg: str | None, csv_file: str | None, skip_header: bool) -> Iterator[str]:
        if session_ids_arg:
            for sid in session_ids_arg.split(","):
                if sid.strip():
                    yield sid.strip()
            return

        if csv_file:
            try:
                with open(csv_file, newline="") as f:
                    reader = csv.reader(f)
                    if skip_header:
                        next(reader, None)
                    for row in reader:
                        if len(row) > 0 and row[0].strip():
                            yield row[0].strip()
            except FileNotFoundError:
                raise CommandError(f"CSV file not found: {csv_file}")
            except PermissionError:
                raise CommandError(f"Permission denied reading CSV file: {csv_file}")
            except OSError as e:
                raise CommandError(f"Error reading CSV file {csv_file}: {e}")

    def _iter_batches(
        self, session_ids_arg: str | None, csv_file: str | None, skip_header: bool, batch_size: int
    ) -> Iterator[list[str]]:
        batch: list[str] = []

        for sid in self._iter_session_ids(session_ids_arg, csv_file, skip_header):
            batch.append(sid)

            if len(batch) >= batch_size:
                yield list(set(batch))
                batch = []

        if batch:
            yield list(set(batch))

    def _count_existing(self, team: Team, session_ids: list[str]) -> int:
        result = sync_execute(
            """
            SELECT count(DISTINCT session_id)
            FROM session_replay_events
            WHERE team_id = %(team_id)s AND session_id IN %(session_ids)s
            """,
            {"team_id": team.pk, "session_ids": session_ids},
        )
        return result[0][0] if result else 0

    def _process_dry_run(
        self, team: Team, session_ids_arg: str | None, csv_file: str | None, skip_header: bool, batch_size: int
    ) -> None:
        total_would_delete = 0
        total_not_found = 0
        total_processed = 0

        for batch in self._iter_batches(session_ids_arg, csv_file, skip_header, batch_size):
            total_processed += len(batch)

            existing_count = self._count_existing(team, batch)
            total_would_delete += existing_count
            total_not_found += len(batch) - existing_count

            self.stdout.write(f"  Processed {total_processed} session IDs...")

        if total_processed == 0:
            self.stdout.write(self.style.WARNING("No session IDs to process"))
            return

        self.stdout.write("")
        self.stdout.write(self.style.NOTICE(f"Would delete {total_would_delete} sessions from ClickHouse"))
        self.stdout.write(self.style.SUCCESS(f"Not found in ClickHouse: {total_not_found} (no action needed)"))

    def _process_deletions(
        self, team: Team, session_ids_arg: str | None, csv_file: str | None, skip_header: bool, batch_size: int
    ) -> None:
        total_processed = 0
        total_batches_deleted = 0

        for batch in self._iter_batches(session_ids_arg, csv_file, skip_header, batch_size):
            total_processed += len(batch)

            query = f"""
                DELETE FROM sharded_session_replay_events
                ON CLUSTER '{CLICKHOUSE_CLUSTER}'
                WHERE team_id = %(team_id)s AND session_id IN %(session_ids)s
            """

            try:
                sync_execute(query, {"team_id": team.pk, "session_ids": batch})
                total_batches_deleted += 1
            except SocketTimeoutError:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Batch {total_batches_deleted + 1} timed out (mutation continues in background)"
                    )
                )
                total_batches_deleted += 1

            self.stdout.write(f"  Processed {total_processed} session IDs...")

        if total_processed == 0:
            self.stdout.write(self.style.WARNING("No session IDs to process"))
            return

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"Issued {total_batches_deleted} delete mutations for {total_processed} session IDs")
        )
        self.stdout.write(self.style.NOTICE("Note: ClickHouse mutations run asynchronously in the background"))
        self.stdout.write(self.style.SUCCESS("Done"))

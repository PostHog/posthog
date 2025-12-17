import csv
from collections.abc import Iterator

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from posthog.models.team.team import Team
from posthog.session_recordings.models.session_recording import SessionRecording

BATCH_SIZE = 1000


class Command(BaseCommand):
    help = "Mark session recordings as deleted by session_id"

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

    def _process_dry_run(
        self, team: Team, session_ids_arg: str | None, csv_file: str | None, skip_header: bool, batch_size: int
    ) -> None:
        total_to_update = 0
        total_to_create = 0
        total_already_deleted = 0
        total_processed = 0

        for batch in self._iter_batches(session_ids_arg, csv_file, skip_header, batch_size):
            total_processed += len(batch)

            existing = set(
                SessionRecording.objects.filter(team=team, session_id__in=batch).values_list("session_id", flat=True)
            )
            already_deleted = set(
                SessionRecording.objects.filter(team=team, session_id__in=batch, deleted=True).values_list(
                    "session_id", flat=True
                )
            )

            total_to_update += len(existing - already_deleted)
            total_to_create += len(set(batch) - existing)
            total_already_deleted += len(already_deleted)

            self.stdout.write(f"  Processed {total_processed} session IDs...")

        if total_processed == 0:
            self.stdout.write(self.style.WARNING("No session IDs to process"))
            return

        self.stdout.write("")
        self.stdout.write(self.style.NOTICE(f"Would update {total_to_update} existing recordings to deleted=True"))
        self.stdout.write(self.style.NOTICE(f"Would create {total_to_create} new recordings with deleted=True"))
        self.stdout.write(self.style.SUCCESS(f"Already deleted: {total_already_deleted} (no action needed)"))

    def _process_deletions(
        self, team: Team, session_ids_arg: str | None, csv_file: str | None, skip_header: bool, batch_size: int
    ) -> None:
        total_updated = 0
        total_created = 0
        total_processed = 0

        for batch in self._iter_batches(session_ids_arg, csv_file, skip_header, batch_size):
            total_processed += len(batch)

            existing_ids = set(
                SessionRecording.objects.filter(team=team, session_id__in=batch).values_list("session_id", flat=True)
            )
            new_ids = set(batch) - existing_ids

            with transaction.atomic():
                not_yet_deleted = Q(deleted__isnull=True) | Q(deleted=False)
                updated_count = (
                    SessionRecording.objects.filter(team=team, session_id__in=existing_ids)
                    .filter(not_yet_deleted)
                    .update(deleted=True)
                )
                total_updated += updated_count

                if new_ids:
                    new_recordings = [SessionRecording(team=team, session_id=sid, deleted=True) for sid in new_ids]
                    SessionRecording.objects.bulk_create(new_recordings, ignore_conflicts=True)
                    total_created += len(new_ids)

            self.stdout.write(f"  Processed {total_processed} session IDs...")

        if total_processed == 0:
            self.stdout.write(self.style.WARNING("No session IDs to process"))
            return

        self.stdout.write("")
        if total_created > 0:
            self.stdout.write(self.style.SUCCESS(f"Created up to {total_created} new recordings with deleted=True"))
        self.stdout.write(self.style.SUCCESS(f"Updated {total_updated} existing recordings to deleted=True"))
        self.stdout.write(self.style.SUCCESS("Done"))

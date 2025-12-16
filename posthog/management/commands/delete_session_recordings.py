import csv
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

import structlog

from posthog.models.team.team import Team
from posthog.session_recordings.models.session_recording import SessionRecording

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Mark session recordings as deleted by session_id"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", required=True, type=int, help="Team ID for the session recordings")
        parser.add_argument("--session-ids", type=str, help="Comma-separated list of session IDs")
        parser.add_argument("--csv-file", type=str, help="Path to CSV file with session IDs (single column)")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")

    def handle(self, *args, **options):
        team_id = options["team_id"]
        session_ids_arg = options["session_ids"]
        csv_file = options["csv_file"]
        dry_run = options["dry_run"]

        if not session_ids_arg and not csv_file:
            raise CommandError("Must provide either --session-ids or --csv-file")

        if session_ids_arg and csv_file:
            raise CommandError("Provide only one of --session-ids or --csv-file, not both")

        team = Team.objects.filter(id=team_id).first()
        if not team:
            raise CommandError(f"Team with ID {team_id} does not exist")

        session_ids = self._collect_session_ids(session_ids_arg, csv_file)
        if not session_ids:
            logger.info("No session IDs to process")
            return

        unique_session_ids = list(set(session_ids))
        logger.info(f"Processing {len(unique_session_ids)} unique session IDs for team {team_id}")

        if dry_run:
            logger.info("Dry run - no changes will be made")
            self._report_plan(team, unique_session_ids)
            return

        self._mark_recordings_deleted(team, unique_session_ids)

    def _collect_session_ids(self, session_ids_arg: str | None, csv_file: str | None) -> list[str]:
        if session_ids_arg:
            return [sid.strip() for sid in session_ids_arg.split(",") if sid.strip()]

        if csv_file:
            session_ids = []
            try:
                with open(csv_file, newline="") as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if row and row[0].strip():
                            session_ids.append(row[0].strip())
            except FileNotFoundError:
                raise CommandError(f"CSV file not found: {csv_file}")
            except PermissionError:
                raise CommandError(f"Permission denied reading CSV file: {csv_file}")
            except OSError as e:
                raise CommandError(f"Error reading CSV file {csv_file}: {e}")
            return session_ids

        return []

    def _report_plan(self, team: Team, session_ids: list[str]) -> None:
        existing = set(
            SessionRecording.objects.filter(team=team, session_id__in=session_ids).values_list("session_id", flat=True)
        )
        already_deleted = set(
            SessionRecording.objects.filter(team=team, session_id__in=session_ids, deleted=True).values_list(
                "session_id", flat=True
            )
        )

        to_update = existing - already_deleted
        to_create = set(session_ids) - existing

        logger.info(f"Would update {len(to_update)} existing recordings to deleted=True")
        logger.info(f"Would create {len(to_create)} new recordings with deleted=True")
        logger.info(f"Already deleted: {len(already_deleted)} (no action needed)")

    def _mark_recordings_deleted(self, team: Team, session_ids: list[str]) -> None:
        existing_ids = set(
            SessionRecording.objects.filter(team=team, session_id__in=session_ids).values_list("session_id", flat=True)
        )
        new_ids = set(session_ids) - existing_ids

        with transaction.atomic():
            not_yet_deleted = Q(deleted__isnull=True) | Q(deleted=False)
            updated_count = (
                SessionRecording.objects.filter(team=team, session_id__in=existing_ids)
                .filter(not_yet_deleted)
                .update(deleted=True)
            )

            if new_ids:
                new_recordings = [SessionRecording(team=team, session_id=sid, deleted=True) for sid in new_ids]
                SessionRecording.objects.bulk_create(new_recordings, ignore_conflicts=True)

        if new_ids:
            logger.info(f"Created up to {len(new_ids)} new recordings with deleted=True")
        logger.info(f"Updated {updated_count} existing recordings to deleted=True")
        logger.info("Done")

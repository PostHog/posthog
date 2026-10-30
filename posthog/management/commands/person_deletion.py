"""Queue person deletions that gave up again.

Usage:
    # Export the task's give-up lines as JSONL, then queue their still-live persons (dry run without --apply):
    python manage.py person_deletion requeue --input gave_up.jsonl --apply
    python manage.py person_deletion requeue --team-id 2 --person-uuid <uuid> --gave-up-at 2026-10-19T12:00:00+00:00

The last attempt of `delete_persons_async` logs "delete_persons_async gave up" with every person it left
undeleted, in the fields this command reads: {team_id, person_uuids, delete_profile, delete_recordings,
gave_up_at}. `requeue` queues through the same path as the persons API. It skips persons that no longer
resolve, and persons deleted after `gave_up_at`, which new events have since revived. The line's unmatched
distinct ids only feed the AI training deletion, so this command does not queue them.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.person.deletion_requeue import PendingDeletion, requeue_deletions


class Command(BaseCommand):
    help = "Queue person deletions that gave up again (dry run unless --apply)."

    def add_arguments(self, parser: CommandParser) -> None:
        actions = parser.add_subparsers(dest="action", required=True, metavar="action")
        requeue = actions.add_parser("requeue", help="DRY RUN unless --apply. Queue still-live persons again.")
        requeue.add_argument("--input", type=Path, default=None, help="JSONL of give-up log lines.")
        requeue.add_argument("--team-id", type=int, default=None, help="With --person-uuid, a deletion given inline.")
        requeue.add_argument("--person-uuid", action="append", default=[], help="Person to delete. Repeatable.")
        requeue.add_argument(
            "--gave-up-at",
            type=datetime.fromisoformat,
            default=None,
            help="With --team-id: skip persons deleted after this time, because new events revived them.",
        )
        requeue.add_argument(
            "--recordings-only",
            action="store_true",
            help="Delete only the persons' recordings, and keep their profiles.",
        )
        requeue.add_argument("--apply", action="store_true", help="Queue. Without it the command only reports.")

    def _log(self, message: str) -> None:
        self.stdout.write(f"{time.strftime('%H:%M:%S')} {message}")
        self.stdout.flush()

    def handle(self, *args: Any, **options: Any) -> None:
        deletions = self._read_deletions(options)
        unguarded = sum(1 for d in deletions if d.gave_up_at is None)
        if unguarded:
            self._log(f"{unguarded} deletions have no gave_up_at, so revived persons in them are not detected")
        mode = "APPLY" if options["apply"] else "DRY RUN"
        results = requeue_deletions(
            deletions,
            apply=options["apply"],
            recordings_only=options["recordings_only"],
            on_result=lambda r: self._log(
                f"team {r.team_id}: {r.outcome}, {r.live}/{r.requested} persons to delete, {r.revived} revived, "
                f"profile {r.delete_profile}, recordings {r.delete_recordings}"
            ),
        )
        queued = sum(r.live for r in results if r.outcome in ("queued", "would_queue"))
        self._log(f"requeue {mode}: {len(results)} deletions, {queued} live persons")
        if not options["apply"]:
            self._log("Dry run: nothing was queued. Pass --apply to queue.")

    @staticmethod
    def _read_deletions(options: dict[str, Any]) -> list[PendingDeletion]:
        if (options["input"] is None) == (options["team_id"] is None):
            raise CommandError("Pass either --input or --team-id with --person-uuid")
        if options["team_id"] is not None:
            if not options["person_uuid"]:
                raise CommandError("--team-id needs at least one --person-uuid")
            return [
                PendingDeletion(
                    team_id=options["team_id"],
                    person_uuids=options["person_uuid"],
                    delete_profile=True,
                    delete_recordings=True,
                    source="command_line",
                    gave_up_at=options["gave_up_at"],
                )
            ]
        deletions = []
        with options["input"].open() as handle:
            for line_number, line in enumerate(handle, start=1):
                try:
                    row = json.loads(line)
                    gave_up_at = row.get("gave_up_at")
                    deletions.append(
                        PendingDeletion(
                            team_id=int(row["team_id"]),
                            person_uuids=[str(u) for u in row["person_uuids"]],
                            delete_profile=bool(row.get("delete_profile", True)),
                            delete_recordings=bool(row.get("delete_recordings", True)),
                            source=str(row.get("source", "input")),
                            gave_up_at=datetime.fromisoformat(gave_up_at) if gave_up_at else None,
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise CommandError(f"{options['input']}:{line_number}: {exc}") from exc
        return deletions

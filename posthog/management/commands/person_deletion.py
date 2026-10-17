"""Find person deletions that never finished, and queue them again.

Usage:
    # Delete tasks a worker took from the broker and never finished, delivered 1 h to 30 d ago:
    python manage.py person_deletion stuck --output stuck.jsonl

    # Queue their still-live persons again (dry run without --apply):
    python manage.py person_deletion requeue --input stuck.jsonl --apply
    python manage.py person_deletion requeue --team-id 2 --person-uuid <uuid> --recordings-only --apply

`stuck` only reads the broker. `requeue` queues through the same path as the persons API, and skips persons
that no longer resolve. Its input is `stuck` output, or JSONL rows of {team_id, person_uuids,
delete_profile, delete_recordings}, for example the fields of the task's "delete_persons_async gave up" log
lines, which name every person a given-up deletion left behind.
"""

import json
import time
import dataclasses
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

import redis

from posthog.models.person.deletion_requeue import PendingDeletion, find_stuck_deletions, requeue_deletions


class Command(BaseCommand):
    help = "Find person deletions that never finished (read-only), and queue them again (dry run unless --apply)."

    def add_arguments(self, parser: CommandParser) -> None:
        actions = parser.add_subparsers(dest="action", required=True, metavar="action")

        stuck = actions.add_parser("stuck", help="Read-only. List delete tasks the broker holds as unacknowledged.")
        stuck.add_argument("--output", type=Path, required=True, help="JSONL to create. Must not exist.")
        stuck.add_argument(
            "--min-age-hours", type=float, default=1.0, help="Only messages delivered at least this long ago."
        )
        stuck.add_argument(
            "--max-age-days", type=float, default=30.0, help="Only messages delivered at most this long ago."
        )

        requeue = actions.add_parser("requeue", help="DRY RUN unless --apply. Queue still-live persons again.")
        requeue.add_argument("--input", type=Path, default=None, help="JSONL of deletions, such as stuck output.")
        requeue.add_argument("--team-id", type=int, default=None, help="With --person-uuid, a deletion given inline.")
        requeue.add_argument("--person-uuid", action="append", default=[], help="Person to delete. Repeatable.")
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
        if options["action"] == "stuck":
            self._stuck(options)
        else:
            self._requeue(options)

    def _stuck(self, options: dict[str, Any]) -> None:
        try:
            out = options["output"].open("x")
        except FileExistsError as exc:
            raise CommandError(f"{options['output']} already exists; choose a new --output") from exc
        client = redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=10)
        found = persons = 0
        with out:
            for deletion in find_stuck_deletions(
                client,
                min_age_seconds=options["min_age_hours"] * 3600,
                max_age_seconds=options["max_age_days"] * 86400,
            ):
                out.write(json.dumps(dataclasses.asdict(deletion)) + "\n")
                found += 1
                persons += len(deletion.person_uuids)
        self._log(f"stuck: {found} delete tasks, {persons} persons; see {options['output']}")

    def _requeue(self, options: dict[str, Any]) -> None:
        deletions = self._read_deletions(options)
        mode = "APPLY" if options["apply"] else "DRY RUN"
        results = requeue_deletions(
            deletions,
            apply=options["apply"],
            recordings_only=options["recordings_only"],
            on_result=lambda r: self._log(
                f"team {r.team_id}: {r.outcome}, {r.live}/{r.requested} persons live, "
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
                )
            ]
        deletions = []
        with options["input"].open() as handle:
            for line_number, line in enumerate(handle, start=1):
                try:
                    row = json.loads(line)
                    deletions.append(
                        PendingDeletion(
                            team_id=int(row["team_id"]),
                            person_uuids=[str(u) for u in row["person_uuids"]],
                            delete_profile=bool(row.get("delete_profile", True)),
                            delete_recordings=bool(row.get("delete_recordings", True)),
                            source=str(row.get("source", "input")),
                            delivered_at=row.get("delivered_at"),
                            retries=row.get("retries"),
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise CommandError(f"{options['input']}:{line_number}: {exc}") from exc
        return deletions

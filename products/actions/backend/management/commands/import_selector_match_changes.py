import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime

from posthog.storage import object_storage

from products.actions.backend.models import Action, ActionSelectorMatchChange

NO_FAITHFUL_FIX = "no_faithful_fix"
OBJECT_URI_SCHEME = "s3://"


def read_report(target: str) -> dict[str, Any]:
    """The audit report at a local path or `s3://<bucket>/<key>`.

    Deliberately not imported from the audit package: the audit runs from a
    checkout in a toolbox pod and need not be deployed, while this command has
    to run wherever the table lives.
    """
    if not target.startswith(OBJECT_URI_SCHEME):
        return json.loads(Path(target).read_text())
    bucket, _, key = target[len(OBJECT_URI_SCHEME) :].partition("/")
    if not bucket or not key:
        raise CommandError(f"expected {OBJECT_URI_SCHEME}<bucket>/<key>, got {target!r}")
    body = object_storage.read(key, bucket=bucket)
    if not body:
        raise CommandError(f"no report at {target}")
    return json.loads(body)


class Command(BaseCommand):
    help = (
        "Import no-faithful-fix selector verdicts from an audit report into the database, so the "
        "action API can tell an owner that the selector compiler change moved their numbers. "
        "Read-only unless --live-run is passed."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--report", required=True, help="Audit report: a local path or s3://<bucket>/<key>")
        parser.add_argument("--live-run", action="store_true", help="Actually write; default is dry-run")

    def handle(self, *args: Any, **options: Any) -> None:
        log = self.stdout.write
        report = read_report(options["report"])
        measured_at = parse_datetime(report.get("generated_at") or "")
        if measured_at is None:
            raise CommandError("report has no usable generated_at timestamp")

        # Keyed by every team the audit covered, not only the affected ones, so a team
        # that no longer has a no-faithful-fix selector has its stored rows cleared
        # rather than left behind to show a notice the latest measurement disowns.
        rows_by_team: dict[int, list[dict[str, Any]]] = {
            int(team_key): [row for row in team.get("rows", []) if row.get("bucket") == NO_FAITHFUL_FIX]
            for team_key, team in report.get("teams", {}).items()
        }
        if not rows_by_team:
            log("report covers no teams; nothing to import")
            return

        total_rows = sum(len(rows) for rows in rows_by_team.values())
        affected_teams = sum(1 for rows in rows_by_team.values() if rows)
        log(
            f"report covers {len(rows_by_team)} teams and holds {total_rows} no-faithful-fix "
            f"selector steps across {affected_teams} of them"
        )

        imported = 0
        stale = 0
        for team_id, rows in sorted(rows_by_team.items()):
            actions = {
                action.id: action
                for action in Action.objects.filter(team_id=team_id, id__in={row["action_id"] for row in rows})
            }
            changes = []
            for row in rows:
                action = actions.get(row["action_id"])
                if action is None or action.deleted:
                    stale += 1
                    continue
                change = ActionSelectorMatchChange(
                    team_id=team_id,
                    action=action,
                    step_index=row["step_index"],
                    selector=row["selector"],
                    old_match_count=row["counts"]["old_original"],
                    new_match_count=row["counts"]["new_original"],
                    measured_at=measured_at,
                )
                if not change.describes(action):
                    stale += 1
                    continue
                changes.append(change)
            imported += len(changes)
            if not options["live_run"]:
                continue
            # The report is authoritative for every team it covers, so replacing
            # the team's rows keeps a re-import from leaving behind verdicts the
            # latest measurement no longer reaches.
            with transaction.atomic():
                # Both reads and writes go through a fail-closed manager, which refuses
                # to build a queryset without a team scope.
                ActionSelectorMatchChange.objects.for_team(team_id).delete()
                ActionSelectorMatchChange.objects.for_team(team_id).bulk_create(changes)

        if options["live_run"]:
            log(self.style.SUCCESS(f"imported {imported} selector match changes, skipped {stale} stale rows"))
        else:
            log(f"dry-run: would import {imported} selector match changes, skipping {stale} stale rows")

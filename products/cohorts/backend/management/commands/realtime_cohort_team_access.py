"""Grant, revoke and list team access to the realtime cohort pipeline, meant for a toolbox pod.

Only Django reads these rows, as a union with its `REALTIME_COHORT_TEAM_ALLOWLIST`. The shuffler,
processor and seeder read their own env lists, so every grant or revoke needs the same change there.

A grant at `processing` gives the team Django's side of the pipeline while its users see none of it,
which is what a load test needs. `serving` also shows them realtime cohort state. `revoke --purpose
load_test` sets every load-test row to `off` at once, and ends no run.

A team on the env list is `serving` whatever its row says, so `grant` and `revoke` refuse it.
"""

import argparse
from datetime import datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.cohorts.backend.models.team_access import (
    RealtimeCohortAccessPurpose,
    RealtimeCohortLevel,
    RealtimeCohortTeamAccess,
)
from products.cohorts.backend.realtime_teams import (
    GrantLevel,
    grant_realtime_cohort_access,
    revoke_realtime_cohort_access,
)

GRANT_LEVELS: dict[str, GrantLevel] = {
    RealtimeCohortLevel.PROCESSING.value: RealtimeCohortLevel.PROCESSING,
    RealtimeCohortLevel.SERVING.value: RealtimeCohortLevel.SERVING,
}
LIST_COLUMNS = ("team_id", "level", "purpose", "save_triggers_backfill", "processing_since", "off_since", "changed_at")


class Command(BaseCommand):
    help = "Grant, revoke and list team access to the realtime cohort pipeline."

    def add_arguments(self, parser: CommandParser) -> None:
        subparsers = parser.add_subparsers(dest="action", required=True)

        grant = subparsers.add_parser("grant", help="Write the teams' access rows, all or none.")
        grant.add_argument("--teams", type=int, nargs="+", required=True)
        grant.add_argument("--purpose", choices=RealtimeCohortAccessPurpose.values, required=True)
        # Required, so that re-running a grant cannot quietly move a serving team down to processing
        # or turn its triggers off.
        grant.add_argument(
            "--level",
            choices=list(GRANT_LEVELS),
            required=True,
            help="processing runs the pipeline unseen by the team's users; serving also shows them its state.",
        )
        grant.add_argument(
            "--save-triggers-backfill",
            action=argparse.BooleanOptionalAction,
            required=True,
            help="Whether a cohort save in these teams enqueues its backfill run.",
        )

        revoke = subparsers.add_parser("revoke", help="Set the selected rows to off, all or none.")
        selector = revoke.add_mutually_exclusive_group(required=True)
        selector.add_argument("--teams", type=int, nargs="+")
        selector.add_argument("--purpose", choices=RealtimeCohortAccessPurpose.values)

        subparsers.add_parser("list", help="Print every access row.")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            match options["action"]:
                case "grant":
                    self._grant(options)
                case "revoke":
                    self._revoke(options)
                case "list":
                    self._list()
        except ValueError as error:
            raise CommandError(str(error)) from error

    def _grant(self, options: dict[str, Any]) -> None:
        granted = grant_realtime_cohort_access(
            options["teams"],
            level=GRANT_LEVELS[options["level"]],
            purpose=RealtimeCohortAccessPurpose(options["purpose"]),
            save_triggers_backfill=options["save_triggers_backfill"],
        )
        self.stdout.write(f"Granted {options['level']} to {_team_list(granted)}")

    def _revoke(self, options: dict[str, Any]) -> None:
        if options["teams"] is not None:
            rows = RealtimeCohortTeamAccess.objects.filter(team_id__in=options["teams"])
        else:
            rows = RealtimeCohortTeamAccess.objects.filter(purpose=options["purpose"])
        revoked = revoke_realtime_cohort_access(rows)
        self.stdout.write(f"Revoked {_team_list(revoked)}" if revoked else "No granted team matched")
        if options["teams"] is not None and (not_granted := sorted(set(options["teams"]) - set(revoked))):
            self.stdout.write(f"Not granted, left as they were: {_team_list(not_granted)}")

    def _list(self) -> None:
        self.stdout.write("\t".join(LIST_COLUMNS))
        for row in RealtimeCohortTeamAccess.objects.order_by("team_id"):
            values = [str(row.team_id), row.level, row.purpose, str(row.save_triggers_backfill)]
            values += [_timestamp(row.processing_since), _timestamp(row.off_since), _timestamp(row.changed_at)]
            self.stdout.write("\t".join(values))


def _team_list(team_ids: list[int]) -> str:
    return f"{len(team_ids)} teams: {', '.join(str(team_id) for team_id in team_ids)}"


def _timestamp(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") if value is not None else "-"

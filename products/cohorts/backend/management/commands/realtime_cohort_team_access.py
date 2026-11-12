"""Enable, grant, revoke and list team access to the realtime cohort pipeline, meant for a toolbox pod.

Django, the shufflers, the processor and the seeder read these rows, each as a union with its own
`REALTIME_COHORT_TEAM_ALLOWLIST`.

`enable` is how a beta team gets realtime cohorts: it prepares the team's cohorts, grants `processing`,
creates the team backfill runs, and moves the team to `serving` once neither run was refused. Run it again
after resolving a refusal.

A grant at `processing` gives the team the pipeline while its users see none of it, which is what a load
test needs. `serving` also shows them realtime cohort state. `revoke --purpose load_test` sets every
load-test row to `off` at once, and ends no run.

A team on the env list is `serving` whatever its row says, so `enable`, `grant` and `revoke` refuse it.
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
from products.cohorts.backend.realtime_enablement import (
    AlreadyServing,
    TeamEnablement,
    describe_enablement,
    enable_realtime_cohorts,
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
# `enable` alone writes beta rows, so a grant cannot skip the preparation it does. A revoked team cannot be
# granted again, so beta customer teams are revoked one id at a time.
NON_BETA_PURPOSES = [
    purpose for purpose in RealtimeCohortAccessPurpose.values if purpose != RealtimeCohortAccessPurpose.BETA
]


class Command(BaseCommand):
    help = "Enable, grant, revoke and list team access to the realtime cohort pipeline."

    def add_arguments(self, parser: CommandParser) -> None:
        subparsers = parser.add_subparsers(dest="action", required=True)

        enable = subparsers.add_parser(
            "enable",
            help="Prepare each beta team's cohorts and backfills, and move it to serving once nothing was refused.",
        )
        enable.add_argument("--teams", type=int, nargs="+", required=True)

        grant = subparsers.add_parser("grant", help="Write the teams' access rows, all or none.")
        grant.add_argument("--teams", type=int, nargs="+", required=True)
        grant.add_argument("--purpose", choices=NON_BETA_PURPOSES, required=True)
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
        selector.add_argument("--purpose", choices=NON_BETA_PURPOSES)

        subparsers.add_parser("list", help="Print every access row.")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            match options["action"]:
                case "enable":
                    self._enable(options["teams"])
                case "grant":
                    self._grant(options)
                case "revoke":
                    self._revoke(options)
                case "list":
                    self._list()
        except ValueError as error:
            raise CommandError(str(error)) from error

    def _enable(self, team_ids: list[int]) -> None:
        not_serving: list[int] = []
        stale_flags_cache: list[int] = []
        for team_id in sorted(set(team_ids)):
            try:
                result = enable_realtime_cohorts(team_id, purpose=RealtimeCohortAccessPurpose.BETA)
            except ValueError as error:
                self.stdout.write(f"Team {team_id}: refused, {error}")
                not_serving.append(team_id)
                continue
            match result:
                case AlreadyServing():
                    self.stdout.write(f"Team {team_id}: already serving")
                case TeamEnablement() as enablement:
                    for line in describe_enablement(team_id, enablement):
                        self.stdout.write(line)
                    if not enablement.promoted:
                        not_serving.append(team_id)
                    if enablement.resave.rebuild_dispatch_failed:
                        stale_flags_cache.append(team_id)
        failures = []
        if not_serving:
            failures.append(f"Not enabled: {', '.join(str(team_id) for team_id in not_serving)}.")
        # A rerun is a no-op once the team serves, so it cannot repair this.
        if stale_flags_cache:
            failures.append(
                f"Flags cache rebuild not enqueued for {', '.join(str(team_id) for team_id in stale_flags_cache)}, "
                "so enqueue update_team_flags_cache and update_team_service_flags_cache for them."
            )
        if failures:
            raise CommandError(" ".join(failures))

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

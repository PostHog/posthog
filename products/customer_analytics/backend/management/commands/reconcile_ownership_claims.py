"""Apply the Salesforce Task decisions in a project's bound warehouse view once, and print what
happened. The Temporal schedule in ``temporal/ownership_claims.py`` does the same for every enabled
project on a timer.

    python manage.py reconcile_ownership_claims --team-id 2
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team import Team

from products.customer_analytics.backend.logic.ownership_claims import (
    ClaimSourceMisconfigured,
    reconcile_ownership_claims,
)


class Command(BaseCommand):
    help = "Apply the Salesforce Task ownership decisions in a project's bound warehouse view."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        team = Team.objects.filter(id=options["team_id"]).first()
        if team is None:
            raise CommandError(f"No team {options['team_id']}")
        try:
            result = reconcile_ownership_claims(team)
        except ClaimSourceMisconfigured as error:
            raise CommandError(str(error))
        if result.skipped:
            self.stdout.write("skipped: claims are disabled or no view is bound for this project")
            return
        summary = ", ".join(f"{outcome}={count}" for outcome, count in sorted(result.outcomes.items()))
        self.stdout.write(f"{result.decisions} decision(s): {summary or 'none'}")

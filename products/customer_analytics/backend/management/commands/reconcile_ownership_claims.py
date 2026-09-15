"""Apply the Salesforce Task decisions in the views bound to a project's controlled relationships
once, and print what happened. The Temporal schedule in ``temporal/ownership_claims.py`` does the
same for every project on a timer. Do not run this while that schedule is sweeping the same project:
of two sweeps at once, the older read can apply a claim the newer one has already seen released.

    python manage.py reconcile_ownership_claims --team-id 2
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team import Team

from products.customer_analytics.backend.logic.ownership_claims import reconcile_ownership_claims


class Command(BaseCommand):
    help = "Apply the Salesforce Task ownership decisions in the views bound to a project's controlled relationships."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        team = Team.objects.filter(id=options["team_id"]).first()
        if team is None:
            raise CommandError(f"No team {options['team_id']}")
        result = reconcile_ownership_claims(team)
        if result.skipped:
            self.stdout.write(
                "skipped: no controlled relationship in this project has a live claim view bound with claims enabled"
            )
            return
        summary = ", ".join(f"{outcome}={count}" for outcome, count in sorted(result.outcomes.items()))
        self.stdout.write(f"{result.decisions} row(s) read: {summary or 'none'}")

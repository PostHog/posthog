"""Run ticket trends/incident detection for one team, immediately and inline.

Used for dogfooding: seed tickets, run this, then check the incidents API,
the $conversation_incident_detected event, and the banner — no Temporal
worker or schedule required (detection is plain Django code).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team

from products.conversations.backend.temporal.trends.detection import run_detection


class Command(BaseCommand):
    help = "Run ticket trends/incident detection for a single team."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--team-id", type=int, required=True)

    def handle(self, *args, **options) -> None:
        team_id: int = options["team_id"]
        if not Team.objects.filter(id=team_id).exists():
            raise CommandError(f"Team {team_id} not found")

        stats = run_detection(team_id)
        self.stdout.write(
            self.style.SUCCESS(
                f"Detection complete: {stats.incidents_fired} incident(s) fired, "
                f"{stats.incidents_resolved} resolved, {stats.rules_evaluated} rule(s) evaluated"
            )
        )

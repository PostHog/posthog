"""Seed a local team with the sample AI traces in `products/ai_observability/fixtures/sample_traces/`.

Local/dev only: events go through the capture service, so the dev stack must be running.

Usage:
    python manage.py seed_ai_sample_traces --team-id 1
    python manage.py seed_ai_sample_traces --team-id 1 --set all
    python manage.py seed_ai_sample_traces --team-id 1 --only claude_code_plugin_session
"""

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models import Team

from products.ai_observability.backend.sample_traces import SampleTraces, seed


class Command(BaseCommand):
    help = "Send the sample AI traces to local capture for one team"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--set", default="core", help="core, stress or all")
        parser.add_argument("--only", help="Comma-separated unit ids or substrings; overrides --set")
        parser.add_argument("--host", default="http://localhost:8010", help="Capture base URL")
        parser.add_argument("--days", type=float, default=7, help="Spread units over this many past days")

    def handle(self, *args: object, **options: object) -> None:
        team = Team.objects.filter(id=options["team_id"]).first()
        if team is None:
            raise CommandError(f"Team {options['team_id']} does not exist")
        days = float(str(options["days"]))
        if not 0 <= days < float("inf"):
            raise CommandError("--days must be a finite, non-negative number")
        only = str(options["only"]).split(",") if options["only"] is not None else None
        try:
            unit_ids = SampleTraces().unit_ids(str(options["set"]), only)
        except ValueError as error:
            raise CommandError(str(error)) from error
        if not unit_ids:
            raise CommandError("No sample unit matches the selection")
        sent = seed(team.api_token, str(options["host"]), unit_ids, days)
        for unit_id, count in sent.items():
            self.stdout.write(f"{unit_id}: {count} events")
        self.stdout.write(
            self.style.SUCCESS(f"Sent {sum(sent.values())} events from {len(sent)} units to team {team.id}")
        )

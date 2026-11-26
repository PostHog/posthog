from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.aeo.backend.facts import backfill_facts
from products.aeo.backend.models import AEOCitationCheck


class Command(BaseCommand):
    help = "Write the cited URL and search rows of checks recorded before those rows existed. Safe to run again."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, help="Only this team. Every team with checks when left out.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_ids = (
            [options["team_id"]]
            if options["team_id"]
            else list(AEOCitationCheck.objects.unscoped().values_list("team_id", flat=True).distinct())
        )
        for team_id in team_ids:
            self.stdout.write(f"team {team_id}: {backfill_facts(team_id)} checks read")

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.aeo.backend.check_brands import teams_with_checks
from products.aeo.backend.check_keywords import enrich_check_keywords


class Command(BaseCommand):
    help = "Write the keyword rows of keywords whose history was never matched against the stored answers. Safe to run again."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, help="Only this team. Every team with checks when left out.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_ids = [options["team_id"]] if options["team_id"] else teams_with_checks()
        for team_id in team_ids:
            result = enrich_check_keywords(team_id)
            self.stdout.write(
                f"team {team_id}: {result.new.keywords} keywords matched over {result.new.checks} checks, "
                f"{result.new.rows} rows"
            )

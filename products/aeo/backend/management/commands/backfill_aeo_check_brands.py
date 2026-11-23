from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.aeo.backend.check_brands import enrich_check_brands, teams_with_checks


class Command(BaseCommand):
    help = (
        "Write the brand rows of checks that have none and of brands whose names changed, and add a catalog "
        "row for every cited domain the catalog lacks. Safe to run again."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, help="Only this team. Every team with checks when left out.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_ids = [options["team_id"]] if options["team_id"] else teams_with_checks()
        for team_id in team_ids:
            result = enrich_check_brands(team_id)
            self.stdout.write(
                f"team {team_id}: {result.brands_added} brands added, {result.stale.brands} brands resolved again, "
                f"{result.unresolved.checks} checks backfilled"
            )

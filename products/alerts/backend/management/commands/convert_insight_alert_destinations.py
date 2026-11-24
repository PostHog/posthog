from typing import Any

from django.core.management.base import BaseCommand

from products.alerts.backend.destination_conversion import SUCCESSFUL_OUTCOMES, convert_team
from products.alerts.backend.facade.destinations import add_conversion_arguments, conversion_report


class Command(BaseCommand):
    help = (
        "Move the stock destinations of one team's platform-owned insight alerts off HogFunctions, onto "
        "destination rows. Reports only, unless --apply is given. Safe to run again."
    )

    def add_arguments(self, parser: Any) -> None:
        add_conversion_arguments(parser)

    def handle(self, *args: Any, **options: Any) -> None:
        conversions = convert_team(options["team_id"], apply=options["apply"])
        for line in conversion_report(
            team_id=options["team_id"],
            apply=options["apply"],
            conversions=conversions,
            converted_outcomes=SUCCESSFUL_OUTCOMES,
        ):
            self.stdout.write(line)

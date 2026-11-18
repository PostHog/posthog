from collections import Counter
from typing import Any

from django.core.management.base import BaseCommand

from products.alerts.backend.platform_cutover import roll_back_team


class Command(BaseCommand):
    help = "Hand one team's insight alerts back from the alerts platform. Safe to run again."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="The team to move back.")

    def handle(self, *args: Any, **options: Any) -> None:
        results = roll_back_team(options["team_id"])
        for result in results:
            if result.skipped is not None:
                self.stdout.write(f"alert={result.alert_id} skipped={result.skipped}")
        outcomes = Counter(str(result.skipped or "moved_back") for result in results)
        self.stdout.write(f"team={options['team_id']} {dict(outcomes) or 'no alerts'}")

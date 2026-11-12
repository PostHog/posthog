from typing import Any

from django.core.management.base import BaseCommand

from products.alerts.backend.platform_subscribers import backfill_subscriber_destinations


class Command(BaseCommand):
    help = (
        "Write each insight alert's subscribers onto its alerts platform copy as email and in-app destinations. "
        "Alerts with no copy are skipped. Safe to run again."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, help="Only this team's alerts.")

    def handle(self, *args: Any, **options: Any) -> None:
        counts = backfill_subscriber_destinations(team_id=options["team_id"])
        self.stdout.write(
            f"Wrote subscribers for {counts.written} alerts. {counts.without_copy} alerts have no platform copy."
        )

from typing import Any

from django.core.management.base import BaseCommand

from products.alerts.backend.platform_alert_backfill import backfill_platform_insight_alert_configurations


class Command(BaseCommand):
    help = "Copy insight alert configurations into the shared alert tables for a parallel evaluation."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Copy one team's configurations only.")

    def handle(self, *args: Any, **options: Any) -> None:
        counts = backfill_platform_insight_alert_configurations(team_id=options["team_id"])
        self.stdout.write(f"Created {counts.created}, updated {counts.updated}, skipped {counts.skipped}")

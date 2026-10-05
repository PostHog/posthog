from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.alerts.backend.platform_alert_backfill import (
    backfill_platform_insight_alert_configurations,
    disable_platform_insight_alert_configurations,
)


class Command(BaseCommand):
    help = "Copy insight alert configurations into the shared alert tables for a parallel evaluation."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Copy one team's configurations only.")
        parser.add_argument(
            "--sample-percent",
            type=int,
            default=100,
            help="Copy only this percentage of alerts, chosen by alert id so a rerun picks the same ones.",
        )
        parser.add_argument(
            "--disable",
            action="store_true",
            help="Copy nothing. Switch off the existing insight copies instead, keeping their history.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["disable"]:
            if options["sample_percent"] != 100:
                raise CommandError("--disable switches off every copy in scope and takes no --sample-percent")
            disabled = disable_platform_insight_alert_configurations(team_id=options["team_id"])
            self.stdout.write(f"Disabled {disabled}")
            return
        try:
            counts = backfill_platform_insight_alert_configurations(
                team_id=options["team_id"], sample_percent=options["sample_percent"]
            )
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            f"Created {counts.created}, updated {counts.updated}, skipped {counts.skipped}, failed {counts.failed}"
        )

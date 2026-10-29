from collections.abc import Collection
from typing import Any
from uuid import UUID

from products.alerts.backend.platform_alert_backfill import (
    BackfillCounts,
    backfill_platform_insight_alert_configurations,
    disable_platform_insight_alert_configurations,
)
from products.alerts_platform.backend.facade.backfill_command import PlatformBackfillCommand


class Command(PlatformBackfillCommand):
    help = "Copy insight alert configurations into the shared alert tables for a parallel evaluation."
    source_name = "insight"
    sample_unit = "alert"
    include_ai_detector = False

    def add_arguments(self, parser: Any) -> None:
        super().add_arguments(parser)
        parser.add_argument(
            "--include-ai-detector",
            action="store_true",
            help="Also copy AI detector alerts. Each of their checks makes a model call the project pays for, "
            "so a copy doubles that cost while both stacks run.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        self.include_ai_detector = options["include_ai_detector"]
        super().handle(*args, **options)

    def backfill(
        self, *, team_id: int | None, sample_percent: int, alert_ids: Collection[UUID] | None
    ) -> BackfillCounts:
        return backfill_platform_insight_alert_configurations(
            team_id=team_id,
            sample_percent=sample_percent,
            alert_ids=alert_ids,
            include_ai_detector=self.include_ai_detector,
        )

    def disable(self, *, team_id: int | None, alert_ids: Collection[UUID] | None) -> int:
        return disable_platform_insight_alert_configurations(team_id=team_id, alert_ids=alert_ids)

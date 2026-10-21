from collections.abc import Collection
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

    def backfill(
        self, *, team_id: int | None, sample_percent: int, alert_ids: Collection[UUID] | None
    ) -> BackfillCounts:
        return backfill_platform_insight_alert_configurations(
            team_id=team_id, sample_percent=sample_percent, alert_ids=alert_ids
        )

    def disable(self, *, team_id: int | None, alert_ids: Collection[UUID] | None) -> int:
        return disable_platform_insight_alert_configurations(team_id=team_id, alert_ids=alert_ids)

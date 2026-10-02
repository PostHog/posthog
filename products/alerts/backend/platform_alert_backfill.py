"""One-way copy of insight alert configurations into the shared alert tables.

The control plane stays with this product: this reads, never writes back, and nothing keeps the
copy in sync afterwards. Run it again to pick up changes.

`legacy_configuration_id` carries the row each copy came from, so a second run updates rather
than duplicates, and the platform's evaluation reads the insight and its bound through it.
"""

import structlog

from posthog.dataclasses import frozen
from posthog.schema_enums import AlertCalculationInterval

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_source_cycle import is_evaluated_on_the_platform
from products.alerts_platform.backend.facade.api import upsert_configuration
from products.alerts_platform.backend.facade.contracts import SOURCE_CONDITION_KEY, PlatformAlertUpsert, SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertConfigurationRecurrenceUnit as RecurrenceUnit

logger = structlog.get_logger(__name__)

# Minutes for the hourly cadence, a calendar unit for the rest. A calendar unit reads its cadence
# from the unit, so its minutes only feed the shard offset, which an anchored unit ignores.
_RECURRENCE: dict[str, tuple[int, str | None]] = {
    AlertCalculationInterval.HOURLY: (60, None),
    AlertCalculationInterval.DAILY: (60 * 24, RecurrenceUnit.DAY),
    AlertCalculationInterval.WEEKLY: (60 * 24 * 7, RecurrenceUnit.WEEK),
    AlertCalculationInterval.MONTHLY: (60 * 24 * 30, RecurrenceUnit.MONTH),
}


@frozen
class BackfillCounts:
    created: int
    updated: int
    skipped: int


def _upsert(alert: AlertConfiguration) -> PlatformAlertUpsert | None:
    """The copy of one alert, or None when the platform does not evaluate it in parallel."""
    recurrence = _RECURRENCE.get(alert.calculation_interval or "")
    if recurrence is None or not is_evaluated_on_the_platform(alert):
        return None
    check_interval_minutes, recurrence_unit = recurrence
    return PlatformAlertUpsert(
        legacy_configuration_id=alert.id,
        team_id=alert.team_id,
        name=alert.name,
        enabled=alert.enabled,
        source_kind=SourceKind.INSIGHT,
        source_config={
            "insight_id": alert.insight_id,
            SOURCE_CONDITION_KEY: {
                "threshold": alert.threshold.configuration if alert.threshold else None,
                "comparison": alert.condition,
            },
        },
        check_interval_minutes=check_interval_minutes,
        recurrence_unit=recurrence_unit,
        # The hourly cadence has no anchor here: production fires it at the alert's creation
        # minute, while sixty minutes on the platform lands on a UTC grid.
        anchor_time=alert.schedule_start_time if recurrence_unit is not None else None,
        evaluation_periods=1,
        datapoints_to_alarm=1,
        cooldown_minutes=0,
        schedule_restriction=alert.schedule_restriction,
        next_check_at=alert.next_check_at,
        snooze_until=alert.snoozed_until,
    )


def backfill_platform_insight_alert_configurations(*, team_id: int | None = None) -> BackfillCounts:
    """Copies every insight alert the platform evaluates in parallel, or one team's."""
    source = AlertConfiguration.objects.select_related("threshold").filter(insight__deleted=False)
    if team_id is not None:
        source = source.filter(team_id=team_id)

    created = 0
    updated = 0
    skipped = 0
    for alert in source.iterator():
        upsert = _upsert(alert)
        if upsert is None:
            skipped += 1
            continue
        if upsert_configuration(upsert):
            created += 1
        else:
            updated += 1

    logger.info(
        "platform_insight_alert_backfill.complete", created=created, updated=updated, skipped=skipped, team_id=team_id
    )
    return BackfillCounts(created=created, updated=updated, skipped=skipped)

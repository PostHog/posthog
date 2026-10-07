"""One-way copy of insight alert configurations into the shared alert tables.

The control plane stays with this product: this reads, never writes back, and nothing keeps the
copy in sync afterwards. Run it again to pick up changes.

`legacy_configuration_id` carries the row each copy came from, so a second run updates rather
than duplicates, and the platform's evaluation reads the insight and its bound through it.
"""

from uuid import UUID

import structlog

from posthog.dataclasses import frozen
from posthog.schema_enums import AlertCalculationInterval

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_source_cycle import is_evaluated_on_the_platform
from products.alerts_platform.backend.facade.api import disable_configurations, upsert_configuration
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
    failed: int


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


def is_sampled(alert_id: UUID, sample_percent: int) -> bool:
    """Whether an alert falls inside a sample. Decided by its id, so a rerun picks the same alerts
    and widening the sample only adds alerts."""
    return alert_id.int % 100 < sample_percent


def backfill_platform_insight_alert_configurations(
    *, team_id: int | None = None, sample_percent: int = 100
) -> BackfillCounts:
    """Copies every insight alert the platform evaluates in parallel, or one team's, or a sample.

    Every copy adds ClickHouse load beside production's, so a rollout copies a sample first and
    widens it while the parallel run's query load stays inside its budget.
    """
    if not 1 <= sample_percent <= 100:
        raise ValueError("sample_percent must be between 1 and 100")
    source = AlertConfiguration.objects.select_related("threshold").filter(insight__deleted=False)
    if team_id is not None:
        source = source.filter(team_id=team_id)

    created = 0
    updated = 0
    skipped = 0
    failed = 0
    for alert in source.iterator():
        upsert = _upsert(alert) if is_sampled(alert.id, sample_percent) else None
        if upsert is None:
            skipped += 1
            continue
        # One alert the copy rejects, such as a start time it cannot parse, must not stop the rest.
        try:
            was_created = upsert_configuration(upsert)
        except Exception:
            logger.exception("platform_insight_alert_backfill.failed", alert_id=str(alert.id), team_id=alert.team_id)
            failed += 1
            continue
        if was_created:
            created += 1
        else:
            updated += 1

    logger.info(
        "platform_insight_alert_backfill.complete",
        created=created,
        updated=updated,
        skipped=skipped,
        failed=failed,
        team_id=team_id,
    )
    return BackfillCounts(created=created, updated=updated, skipped=skipped, failed=failed)


def disable_platform_insight_alert_configurations(*, team_id: int | None = None) -> int:
    """Stops the parallel run for every insight copy, or one team's. Returns how many it stopped.

    The copies stay, with their state and history. Running the backfill again turns them back on.
    """
    disabled = disable_configurations(SourceKind.INSIGHT, team_id=team_id)
    logger.info("platform_insight_alert_backfill.disabled", disabled=disabled, team_id=team_id)
    return disabled

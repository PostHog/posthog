"""One-way copy of billing alert configurations into the shared alert tables.

The control plane stays with this product: this reads, never writes back, and nothing keeps the
copy in sync afterwards. Run it again to pick up changes.

`legacy_configuration_id` carries the row each copy came from, so a second run updates rather
than duplicates, and the platform's evaluation reads the alert through it.
"""

from uuid import UUID

import structlog

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.api import disable_configurations, upsert_configuration
from products.alerts_platform.backend.facade.contracts import SOURCE_CONDITION_KEY, PlatformAlertUpsert, SourceKind
from products.billing_alerts.backend.models import BillingAlertConfiguration

logger = structlog.get_logger(__name__)

CHECK_INTERVAL_MINUTES = 60


@frozen
class BackfillCounts:
    created: int
    updated: int
    skipped: int
    failed: int


def _upsert(alert: BillingAlertConfiguration) -> PlatformAlertUpsert | None:
    """The copy of one alert, or None when it has no execution team to run under."""
    if alert.team_id is None:
        return None
    return PlatformAlertUpsert(
        legacy_configuration_id=alert.id,
        team_id=alert.team_id,
        name=alert.name,
        enabled=alert.enabled,
        source_kind=SourceKind.BILLING,
        source_config={
            "organization_id": str(alert.organization_id),
            # Decimals as strings, because the column is JSON and a float would round the bound.
            SOURCE_CONDITION_KEY: {
                "metric": alert.metric,
                "threshold_value": None if alert.threshold_value is None else str(alert.threshold_value),
            },
        },
        check_interval_minutes=CHECK_INTERVAL_MINUTES,
        evaluation_periods=1,
        datapoints_to_alarm=1,
        # Billing's cooldown spaced its daily reminders. The platform sends no reminders, and under
        # its policy a cooldown also holds back the resolve when a billing period rolls over.
        cooldown_minutes=0,
        schedule_restriction=None,
        # A new copy runs on the next tick. A rerun keeps the schedule the platform already holds.
        next_check_at=None,
        # The adapter reads the snooze off the billing row on every check. A copied snooze would keep
        # the copy muted after someone unsnoozes the billing alert.
        snooze_until=None,
    )


def is_sampled(alert_id: UUID, sample_percent: int) -> bool:
    """Whether an alert falls inside a sample. Decided by its id, so a rerun picks the same alerts
    and widening the sample only adds alerts."""
    return alert_id.int % 100 < sample_percent


def backfill_platform_billing_alert_configurations(
    *, team_id: int | None = None, sample_percent: int = 100
) -> BackfillCounts:
    """Copies every billing alert, or one team's, or a sample.

    Every copy adds billing service calls, so a rollout copies a sample first and widens it while
    the load on that service stays flat.
    """
    if not 1 <= sample_percent <= 100:
        raise ValueError("sample_percent must be between 1 and 100")
    source = BillingAlertConfiguration.objects.all()
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
        try:
            was_created = upsert_configuration(upsert)
        except Exception:
            logger.exception("platform_billing_alert_backfill.failed", alert_id=str(alert.id), team_id=alert.team_id)
            failed += 1
            continue
        if was_created:
            created += 1
        else:
            updated += 1

    logger.info(
        "platform_billing_alert_backfill.complete",
        created=created,
        updated=updated,
        skipped=skipped,
        failed=failed,
        team_id=team_id,
    )
    return BackfillCounts(created=created, updated=updated, skipped=skipped, failed=failed)


def disable_platform_billing_alert_configurations(*, team_id: int | None = None) -> int:
    """Stops platform evaluation for every billing copy, or one team's. Returns how many it stopped.

    The copies stay, with their state and history. Running the backfill again turns them back on.
    """
    disabled = disable_configurations(SourceKind.BILLING, team_id=team_id)
    logger.info("platform_billing_alert_backfill.disabled", disabled=disabled, team_id=team_id)
    return disabled

"""One-way copy of insight alert configurations into the shared alert tables.

The control plane stays with this product: this reads, never writes back, and nothing keeps the
copy in sync afterwards. Run it again to pick up changes.

`legacy_configuration_id` carries the row each copy came from, so a second run updates rather
than duplicates, and the platform's evaluation reads the insight and its bound through it.
"""

from collections.abc import Collection
from uuid import UUID

import structlog

from posthog.dataclasses import frozen

from products.alerts.backend.llm_detector_limits import is_llm_detector_config
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_source_cycle import platform_upsert_of
from products.alerts_platform.backend.facade.api import disable_configurations, upsert_configuration, upsert_if_running
from products.alerts_platform.backend.facade.contracts import SourceKind

logger = structlog.get_logger(__name__)


@frozen
class BackfillCounts:
    created: int
    updated: int
    skipped: int
    failed: int


def is_sampled(alert_id: UUID, sample_percent: int) -> bool:
    """Whether an alert falls inside a sample. Decided by its id, so a rerun picks the same alerts
    and widening the sample only adds alerts."""
    return alert_id.int % 100 < sample_percent


def backfill_platform_insight_alert_configurations(
    *,
    team_id: int | None = None,
    sample_percent: int = 100,
    alert_ids: Collection[UUID] | None = None,
    include_ai_detector: bool = False,
) -> BackfillCounts:
    """Copies every insight alert the platform evaluates in parallel, or one team's, or a sample, or named alerts.

    Every copy adds ClickHouse load beside production's, so a rollout copies a sample first and
    widens it while the parallel run's query load stays inside its budget. Named alerts let a
    rollout copy the ones a comparison still lacks evidence for.

    AI detector alerts are left out unless `include_ai_detector` is set. Each of their checks makes
    a model call that the project pays for, so a parallel copy doubles that cost.
    """
    if not 1 <= sample_percent <= 100:
        raise ValueError("sample_percent must be between 1 and 100")
    source = AlertConfiguration.objects.select_related("threshold").filter(insight__deleted=False)
    if team_id is not None:
        source = source.filter(team_id=team_id)
    if alert_ids is not None:
        source = source.filter(id__in=alert_ids)

    created = 0
    updated = 0
    skipped = 0
    failed = 0
    for alert in source.iterator():
        copied = is_sampled(alert.id, sample_percent) and (
            include_ai_detector or not is_llm_detector_config(alert.detector_config)
        )
        upsert = platform_upsert_of(alert) if copied else None
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


def disable_platform_insight_alert_configurations(
    *, team_id: int | None = None, alert_ids: Collection[UUID] | None = None
) -> int:
    """Stops the parallel run for every insight copy, or one team's, or named alerts'. Returns how many it stopped.

    The copies stay, with their state and history. Running the backfill again turns them back on.
    """
    disabled = disable_configurations(SourceKind.INSIGHT, team_id=team_id, legacy_configuration_ids=alert_ids)
    logger.info("platform_insight_alert_backfill.disabled", disabled=disabled, team_id=team_id)
    return disabled


def follow_insight_alert(alert: AlertConfiguration) -> None:
    """Copies an insight alert that was just created or turned back on, if its team runs insight on the platform.

    Checks only read enabled copies, so no check would ever see this alert otherwise, and it would
    stay off the platform until the next backfill.

    An AI detector alert is never followed. The backfill copies those only when an operator asks,
    and a copy's stored detector is what records that request, so following would overwrite it.
    """
    if is_llm_detector_config(alert.detector_config):
        return
    upsert = platform_upsert_of(alert)
    if upsert is not None:
        upsert_if_running(upsert, revive=True)

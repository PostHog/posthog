"""The insight side of the alerts platform comparison contract.

Production insight writes an `AlertCheck` row for every check, carrying the state that check left
the alert in. So, unlike logs, nothing is reconstructed: production's verdict is a row.

A platform check names its due slot, and the two stacks do not check at the same minute. Production
checks an hourly alert at the minute it was created, while the platform checks on a UTC grid. So the
state production held at the platform's instant is usually its previous period's verdict. Instead, a
platform check pairs with production's first check in the same period: at or after the slot, and
before one interval has passed. A production stack that made no check in that period is behind.

`AlertCheck` rows are deleted after `AlertCheck.RETENTION`, so an older slot cannot be answered.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from django.db.models import Q

import structlog

from posthog.dataclasses import frozen
from posthog.schema_enums import AlertCalculationInterval
from posthog.tasks.alerts.schedule_restriction import is_utc_datetime_blocked

from products.alerts.backend.insight_alert_state_machine import INSIGHT_ALERT_POLICY, platform_state_of
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.alerts.backend.platform_source_cycle import CAPACITY_REJECTED, slot_of_evaluation_key
from products.alerts_platform.backend.facade.contracts import (
    CheckRef,
    IntentionalDivergence,
    PlatformCheck,
    SourceCorrespondence,
    SourceCoverage,
    SourceKind,
    SourceVerdict,
    SuppressionReason,
)
from products.alerts_platform.backend.facade.lifecycle import AlertState
from products.alerts_platform.backend.facade.scheduling import is_weekend

logger = structlog.get_logger(__name__)

# The bound the retention does not give: an hourly alert holds 336 rows, and alerts add up.
MAX_CHECKS_PER_BATCH = 100_000

# How long after its slot production may still make its check of the same period. A month is the
# longest calendar unit insight evaluates on.
_PERIOD: dict[str, timedelta] = {
    AlertCalculationInterval.HOURLY: timedelta(hours=1),
    AlertCalculationInterval.DAILY: timedelta(days=1),
    AlertCalculationInterval.WEEKLY: timedelta(days=7),
    AlertCalculationInterval.MONTHLY: timedelta(days=31),
}


def _refused_for_capacity(check: PlatformCheck, verdict: SourceVerdict) -> bool:
    return check.error_message == CAPACITY_REJECTED


INSIGHT_INTENTIONAL_DIVERGENCES: tuple[IntentionalDivergence, ...] = (
    IntentionalDivergence(
        cause="platform_refused_for_capacity",
        recognizes=_refused_for_capacity,
        why=(
            "The parallel run queries as its own ClickHouse user, under a cap of its own, so "
            "ClickHouse can refuse its query for load where production's ran. The platform then "
            "keeps its state and production holds a verdict. Every other platform error is left "
            "to read as real, so a broken grant or query is not excused."
        ),
    ),
)


@frozen
class _Pairing:
    check: PlatformCheck
    alert_id: UUID
    slot: datetime


@frozen
class _ProductionCheck:
    id: UUID
    created_at: datetime
    # None for a spelling the platform does not have, which is answered as unknown.
    state: str | None
    skipped: bool


class InsightCorrespondence(SourceCorrespondence):
    source = SourceKind.INSIGHT
    # The platform adapter runs production's own policy, so the comparison stays meaningful.
    production_policy = INSIGHT_ALERT_POLICY
    platform_policy = INSIGHT_ALERT_POLICY
    intentional_divergences = INSIGHT_INTENTIONAL_DIVERGENCES

    def verdicts_for(self, checks: Sequence[PlatformCheck]) -> Mapping[CheckRef, SourceVerdict]:
        verdicts: dict[CheckRef, SourceVerdict] = {}
        by_team: dict[int, list[_Pairing]] = defaultdict(list)
        kept_since = datetime.now(UTC) - AlertCheck.RETENTION
        for check in checks:
            slot = slot_of_evaluation_key(check.evaluation_key)
            if check.legacy_configuration_id is None:
                verdicts[check.ref] = _unknown("the platform configuration names no insight alert")
            elif slot is None:
                verdicts[check.ref] = _unknown("the evaluation key names no due slot")
            elif slot < kept_since:
                verdicts[check.ref] = _unknown("production no longer keeps its checks from this slot")
            elif check.state == AlertState.SNOOZED:
                # Both stacks hold the alert snoozed off the same production snooze and evaluate nothing.
                verdicts[check.ref] = SourceVerdict(
                    coverage=SourceCoverage.SUPPRESSED,
                    state=AlertState.SNOOZED.value,
                    suppressed_by=SuppressionReason.MUTED,
                    caught_up_at=None,
                )
            else:
                by_team[check.team_id].append(_Pairing(check=check, alert_id=check.legacy_configuration_id, slot=slot))

        for team_id, pairings in by_team.items():
            verdicts.update(_team_verdicts(team_id, pairings))
        return verdicts


def _team_verdicts(team_id: int, pairings: list[_Pairing]) -> dict[CheckRef, SourceVerdict]:
    alerts = {
        alert.id: alert
        for alert in AlertConfiguration.objects.filter(
            team_id=team_id, id__in={pairing.alert_id for pairing in pairings}
        )
        .select_related("team")
        .only(
            "id",
            "team_id",
            "team__timezone",
            "calculation_interval",
            "enabled",
            "skip_weekend",
            "schedule_restriction",
        )
    }
    earliest: dict[UUID, datetime] = {}
    for pairing in pairings:
        if pairing.alert_id in alerts:
            earliest[pairing.alert_id] = min(pairing.slot, earliest.get(pairing.alert_id, pairing.slot))

    rows = []
    if earliest:
        # Each alert from its own earliest slot, so one old slot does not widen every alert's read.
        since = Q()
        for alert_id, slot in earliest.items():
            since |= Q(alert_configuration_id=alert_id, created_at__gte=slot)
        rows = list(
            AlertCheck.objects.filter(since, alert_configuration__team_id=team_id)
            .order_by("alert_configuration_id", "created_at")
            .values_list("alert_configuration_id", "id", "created_at", "state", "triggered_metadata")[
                : MAX_CHECKS_PER_BATCH + 1
            ]
        )
    if len(rows) > MAX_CHECKS_PER_BATCH:
        logger.warning("Insight alert comparison could not read every check it needs", team_id=team_id)
        return {
            pairing.check.ref: _unknown("too many insight checks to pair this check against") for pairing in pairings
        }

    history: dict[UUID, list[_ProductionCheck]] = defaultdict(list)
    for alert_id, check_id, created_at, state, metadata in rows:
        history[alert_id].append(
            _ProductionCheck(
                id=check_id,
                created_at=created_at,
                state=_platform_state(state),
                skipped=bool((metadata or {}).get("skipped_reason")),
            )
        )

    times = {alert_id: [row.created_at for row in checks] for alert_id, checks in history.items()}
    verdicts: dict[CheckRef, SourceVerdict] = {}
    for pairing in pairings:
        alert = alerts.get(pairing.alert_id)
        if alert is None:
            verdicts[pairing.check.ref] = _unknown("no insight alert with that id in this project")
            continue
        period = _PERIOD.get(alert.calculation_interval)
        if period is None:
            verdicts[pairing.check.ref] = _unknown("the insight alert's interval has no period to pair within")
            continue
        verdicts[pairing.check.ref] = _verdict_at(
            pairing, alert, period, history[pairing.alert_id], times.get(pairing.alert_id, [])
        )
    return verdicts


def _platform_state(insight_state: str) -> str | None:
    try:
        return platform_state_of(insight_state).value
    except (ValueError, KeyError):
        return None


def _unknown(detail: str) -> SourceVerdict:
    return SourceVerdict(caught_up_at=None, coverage=SourceCoverage.UNKNOWN, state=None, detail=detail)


def _verdict_at(
    pairing: _Pairing,
    alert: AlertConfiguration,
    period: timedelta,
    rows: Sequence[_ProductionCheck],
    times: Sequence[datetime],
) -> SourceVerdict:
    """Production's first check of the slot's period, when it left that state, and when it reached
    the platform's state."""
    check = pairing.check
    index = bisect_left(times, pairing.slot)
    if index == len(rows) or rows[index].created_at >= pairing.slot + period:
        return _no_check_in_period(pairing.slot, alert)

    matched = rows[index]
    if matched.skipped:
        return _unknown("production skipped this check without evaluating it")
    if matched.state is None:
        return _unknown("production recorded a state the platform does not spell")
    left = next((row for row in rows[index + 1 :] if row.state != matched.state), None)
    caught_up = next(
        (row for row in rows[index:] if row.created_at > check.occurred_at and row.state == check.state), None
    )
    return SourceVerdict(
        coverage=SourceCoverage.EVALUATED,
        state=matched.state,
        observed_at=left.created_at if left is not None else None,
        caught_up_at=caught_up.created_at if caught_up is not None else None,
        evidence_id=str(matched.id),
    )


def _no_check_in_period(slot: datetime, alert: AlertConfiguration) -> SourceVerdict:
    """Why production made no check of the slot's period. The alert's current settings stand in for
    its settings at the slot, because production keeps no history of them."""
    if not alert.enabled:
        # The copy kept checking an alert production switched off, so the backfill is out of date.
        return SourceVerdict(
            caught_up_at=None,
            coverage=SourceCoverage.SUPPRESSED,
            state=None,
            suppressed_by=SuppressionReason.DISABLED,
        )
    if (alert.skip_weekend and is_weekend(slot, alert.team.timezone)) or is_utc_datetime_blocked(alert, slot):
        # Both stacks skip the slot by the alert's schedule, so neither has a verdict to compare.
        return _unknown("production skips this slot by the alert's schedule")
    return SourceVerdict(
        caught_up_at=None,
        coverage=SourceCoverage.BEHIND,
        state=None,
        detail="production made no check of this alert in the slot's period",
    )

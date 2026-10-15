"""The insight side of the alerts platform comparison contract.

Production insight writes an `AlertCheck` row for every check, carrying the state that check left
the alert in. So, unlike logs, nothing is reconstructed: production's verdict is a row.

A platform check names its due slot, and the two stacks do not check at the same minute. Each
spreads its alerts over an offset within the period, keyed on its own id for the alert, so
production's check of a period can come before the platform's slot or after it. A platform check
pairs with production's first check in the same local calendar period: the quarter hour, hour,
day, ISO week or month the slot falls in. A production stack that made no check in that period is
behind.

`AlertCheck` rows are deleted after `AlertCheck.RETENTION`, so an older slot cannot be answered.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from django.db.models import Q

import pytz
import structlog
from dateutil.relativedelta import relativedelta

from posthog.dataclasses import frozen
from posthog.schema_enums import (
    AlertCalculationInterval,
    AlertState as InsightAlertState,
)
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
from products.alerts_platform.backend.facade.scheduling import is_weekend, local_period_start, next_local_period_start

logger = structlog.get_logger(__name__)

# The bound the retention does not give: an hourly alert holds 336 rows, and alerts add up.
MAX_CHECKS_PER_BATCH = 100_000
# Alerts per history query, so one statement never carries a condition per alert of a large team.
ALERTS_PER_QUERY = 500

# Sub-day periods take their boundaries from the scheduler production uses, which finds them on the
# local wall clock and so follows a 30-minute daylight-saving change.
_SUB_DAY_PERIOD_MINUTES: dict[str, int] = {
    AlertCalculationInterval.EVERY_15_MINUTES: 15,
    AlertCalculationInterval.HOURLY: 60,
}
# Calendar periods follow the team's local calendar: a day across a daylight-saving change is 23 or
# 25 hours, and a month is as long as it is.
_CALENDAR_PERIOD: dict[str, relativedelta] = {
    AlertCalculationInterval.DAILY: relativedelta(days=1),
    AlertCalculationInterval.WEEKLY: relativedelta(weeks=1),
    AlertCalculationInterval.MONTHLY: relativedelta(months=1),
}

# How far past a check's period the read reaches for when production next moved state. A catch-up
# later than this reads as never, which the comparison's lag buckets already treat as the long tail.
CATCH_UP_HORIZON = timedelta(days=1)


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
class _Period:
    start: datetime
    end: datetime


@frozen
class _ProductionCheck:
    id: UUID
    created_at: datetime
    # None for a spelling the platform does not have, which is answered as unknown.
    state: str | None
    skipped: bool


@frozen
class _History:
    """One alert's production checks, oldest first, indexed so each pairing is a few lookups."""

    rows: list[_ProductionCheck]
    times: list[datetime]
    # For each row, the next row whose state differs, or None.
    next_change: list[int | None]
    # When production's evaluated checks held each state. A skipped check confirms nothing.
    evaluated_times: dict[str, list[datetime]]

    @classmethod
    def of(cls, rows: list[_ProductionCheck]) -> _History:
        next_change: list[int | None] = [None] * len(rows)
        for i in range(len(rows) - 2, -1, -1):
            next_change[i] = i + 1 if rows[i + 1].state != rows[i].state else next_change[i + 1]
        evaluated_times: dict[str, list[datetime]] = defaultdict(list)
        for row in rows:
            if row.state is not None and not row.skipped:
                evaluated_times[row.state].append(row.created_at)
        return cls(
            rows=rows,
            times=[row.created_at for row in rows],
            next_change=next_change,
            evaluated_times=dict(evaluated_times),
        )


class InsightCorrespondence(SourceCorrespondence):
    source = SourceKind.INSIGHT
    # The platform adapter runs production's own policy, so the comparison stays meaningful.
    production_policy = INSIGHT_ALERT_POLICY
    platform_policy = INSIGHT_ALERT_POLICY
    intentional_divergences = INSIGHT_INTENTIONAL_DIVERGENCES

    def verdicts_for(self, checks: Sequence[PlatformCheck]) -> Mapping[CheckRef, SourceVerdict]:
        verdicts: dict[CheckRef, SourceVerdict] = {}
        by_team: dict[int, list[_Pairing]] = defaultdict(list)
        for check in checks:
            slot = slot_of_evaluation_key(check.evaluation_key)
            if check.legacy_configuration_id is None:
                verdicts[check.ref] = _unknown("the platform configuration names no insight alert")
            elif slot is None:
                verdicts[check.ref] = _unknown("the evaluation key names no due slot")
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
    periods: dict[CheckRef, _Period | None] = {
        pairing.check.ref: _period_of(pairing.slot, alerts[pairing.alert_id])
        for pairing in pairings
        if pairing.alert_id in alerts
    }
    bounds: dict[UUID, _Period] = {}
    for pairing in pairings:
        period = periods.get(pairing.check.ref)
        if period is not None:
            known = bounds.get(pairing.alert_id, period)
            bounds[pairing.alert_id] = _Period(start=min(known.start, period.start), end=max(known.end, period.end))

    rows: list[tuple[UUID, UUID, datetime, str, dict | None]] = []
    alert_bounds = list(bounds.items())
    for chunk_start in range(0, len(alert_bounds), ALERTS_PER_QUERY):
        # Each alert over its own periods, so one old slot does not widen every alert's read.
        # Built in one step, because growing a Q with |= copies its children on every alert.
        since = Q(
            *(
                Q(
                    alert_configuration_id=alert_id,
                    created_at__gte=bound.start,
                    created_at__lt=bound.end + CATCH_UP_HORIZON,
                )
                for alert_id, bound in alert_bounds[chunk_start : chunk_start + ALERTS_PER_QUERY]
            ),
            _connector=Q.OR,
        )
        rows.extend(
            AlertCheck.objects.filter(since, alert_configuration__team_id=team_id)
            .order_by("alert_configuration_id", "created_at")
            .values_list("alert_configuration_id", "id", "created_at", "state", "triggered_metadata")[
                : MAX_CHECKS_PER_BATCH + 1 - len(rows)
            ]
        )
        if len(rows) > MAX_CHECKS_PER_BATCH:
            break
    if len(rows) > MAX_CHECKS_PER_BATCH:
        logger.warning("Insight alert comparison could not read every check it needs", team_id=team_id)
        return {
            pairing.check.ref: _unknown("too many insight checks to pair this check against") for pairing in pairings
        }

    checks: dict[UUID, list[_ProductionCheck]] = defaultdict(list)
    for alert_id, check_id, created_at, state, metadata in rows:
        if state == InsightAlertState.SNOOZED:
            # Snoozing writes a row carrying the snoozed state, which no evaluation produces. An unsnooze
            # row looks like a healthy breakdown evaluation (no value, no error), so it stays.
            continue
        skipped = bool((metadata or {}).get("skipped_reason"))
        checks[alert_id].append(
            _ProductionCheck(
                id=check_id,
                created_at=created_at,
                state=_platform_state(state),
                skipped=skipped,
            )
        )

    history = {alert_id: _History.of(alert_rows) for alert_id, alert_rows in checks.items()}
    kept_since = datetime.now(UTC) - AlertCheck.RETENTION
    verdicts: dict[CheckRef, SourceVerdict] = {}
    for pairing in pairings:
        alert = alerts.get(pairing.alert_id)
        if alert is None:
            verdicts[pairing.check.ref] = _unknown("no insight alert with that id in this project")
            continue
        if pairing.check.state == AlertState.SNOOZED:
            verdicts[pairing.check.ref] = _snoozed(alert)
            continue
        period = periods.get(pairing.check.ref)
        if period is None:
            verdicts[pairing.check.ref] = _unknown("the insight alert's interval has no period to pair within")
            continue
        # The period, not the slot: production's check of the period can come before the slot.
        if period.start < kept_since:
            verdicts[pairing.check.ref] = _unknown("production no longer keeps its checks from this period")
            continue
        # The platform tests its schedule when it decides, which can be later than the slot.
        if _skipped_by_schedule(pairing.check.occurred_at, alert):
            # Both stacks skip the slot by the alert's schedule, so the platform has no verdict to compare.
            verdicts[pairing.check.ref] = _unknown("the alert's schedule skips this slot")
            continue
        verdicts[pairing.check.ref] = _verdict_at(pairing, alert, period, history.get(pairing.alert_id, _EMPTY))
    return verdicts


def _period_of(slot: datetime, alert: AlertConfiguration) -> _Period | None:
    """The local calendar period the slot falls in: its quarter hour, hour, day, ISO week or month.

    Both schedulers check once per such period, each at an offset of its own, so production's check
    of the same period can come before the platform's slot as well as after it.
    """
    interval = alert.calculation_interval or ""
    if interval in _SUB_DAY_PERIOD_MINUTES:
        minutes = _SUB_DAY_PERIOD_MINUTES[interval]
        team_timezone = pytz.timezone(alert.team.timezone)
        start = local_period_start(slot, team_timezone, minutes)
        return _Period(start=start, end=next_local_period_start(start, team_timezone, minutes))
    if interval not in _CALENDAR_PERIOD:
        return None
    local = slot.astimezone(alert.team.timezone_info)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if interval == AlertCalculationInterval.WEEKLY:
        midnight -= relativedelta(days=midnight.weekday())
    elif interval == AlertCalculationInterval.MONTHLY:
        midnight = midnight.replace(day=1)
    return _Period(start=midnight.astimezone(UTC), end=(midnight + _CALENDAR_PERIOD[interval]).astimezone(UTC))


def _platform_state(insight_state: str) -> str | None:
    try:
        return platform_state_of(insight_state).value
    except (ValueError, KeyError):
        return None


def _unknown(detail: str) -> SourceVerdict:
    return SourceVerdict(caught_up_at=None, coverage=SourceCoverage.UNKNOWN, state=None, detail=detail)


_EMPTY = _History.of([])


def _verdict_at(pairing: _Pairing, alert: AlertConfiguration, period: _Period, history: _History) -> SourceVerdict:
    """Production's first check of the slot's period, when it left that state, and when an evaluated
    check of production's reached the platform's state."""
    index = bisect_left(history.times, period.start)
    if index == len(history.rows) or history.rows[index].created_at >= period.end:
        return _no_check_in_period(alert)

    matched = history.rows[index]
    if matched.skipped:
        return _unknown("production skipped this check without evaluating it")
    if matched.state is None:
        return _unknown("production recorded a state the platform does not spell")
    left = history.next_change[index]
    reached = history.evaluated_times.get(pairing.check.state, [])
    caught_up = bisect_right(reached, pairing.check.occurred_at)
    return SourceVerdict(
        coverage=SourceCoverage.EVALUATED,
        state=matched.state,
        observed_at=history.times[left] if left is not None else None,
        caught_up_at=reached[caught_up] if caught_up < len(reached) else None,
        evidence_id=str(matched.id),
    )


def _skipped_by_schedule(at: datetime, alert: AlertConfiguration) -> bool:
    """Whether the alert's schedule skips a check at `at`. The alert's current settings stand in for
    its settings then, because production keeps no history of them."""
    return (alert.skip_weekend and is_weekend(at, alert.team.timezone)) or is_utc_datetime_blocked(alert, at)


def _snoozed(alert: AlertConfiguration) -> SourceVerdict:
    """A platform check that held the alert snoozed. Both stacks read the same production snooze and
    evaluate nothing, unless production has since switched the alert off."""
    if not alert.enabled:
        return SourceVerdict(
            caught_up_at=None,
            coverage=SourceCoverage.SUPPRESSED,
            state=None,
            suppressed_by=SuppressionReason.DISABLED,
        )
    return SourceVerdict(
        coverage=SourceCoverage.SUPPRESSED,
        state=AlertState.SNOOZED.value,
        suppressed_by=SuppressionReason.MUTED,
        caught_up_at=None,
    )


def _no_check_in_period(alert: AlertConfiguration) -> SourceVerdict:
    """Why production made no check of the slot's period."""
    if not alert.enabled:
        # The copy kept checking an alert production switched off, so the backfill is out of date.
        return SourceVerdict(
            caught_up_at=None,
            coverage=SourceCoverage.SUPPRESSED,
            state=None,
            suppressed_by=SuppressionReason.DISABLED,
        )
    return SourceVerdict(
        caught_up_at=None,
        coverage=SourceCoverage.BEHIND,
        state=None,
        detail="production made no check of this alert in the slot's period",
    )

"""Evaluation of due insight alerts on the shared alerts platform.

A parallel run. The production insight fleet evaluates the same alerts against
`AlertConfiguration` and is the only stack that notifies anyone. This decides what the platform
would have said and delivers nothing.

Each platform row resolves to its production alert through `legacy_configuration_id`, because
`check_alert_for_insight` reads the insight, the threshold and the condition off that model. The
query runs the way production runs it, and the verdict comes from the shared machine under
`INSIGHT_ALERT_POLICY`, applied to the platform's own state. `add_alert_check` is the production
writer, and nothing here calls it.

A check that production skips without a query is skipped here too, so both stacks answer the
same set of checks.
"""

import time
from dataclasses import replace
from datetime import UTC, datetime

from django.conf import settings

import structlog

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.errors import CH_TRANSIENT_ERRORS, QueryErrorCategory, classify_query_error
from posthog.schema_enums import AlertCalculationInterval
from posthog.tasks.alerts.schedule_restriction import is_utc_datetime_blocked
from posthog.tasks.alerts.utils import skip_because_of_weekend
from posthog.temporal.alerts.admission import admit_evaluation_slots, release_evaluation_slot

from products.alerts.backend.evaluation import check_alert_for_insight
from products.alerts.backend.evaluation.contract import AlertExtractionError
from products.alerts.backend.insight_alert_state_machine import INSIGHT_ALERT_POLICY, insight_snapshot
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts_platform.backend.facade.api import due_checks, slot_of
from products.alerts_platform.backend.facade.contracts import (
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    SkipReason,
    SourceKind,
)
from products.alerts_platform.backend.facade.lifecycle import (
    NOTIFICATION_EVENT_KINDS,
    AlertSnapshot,
    AlertState,
    CheckInput,
    ControlPlaneOutcome,
    NotificationAction,
    Outcome,
    apply_snooze,
    apply_unsnooze,
    decide_firing_episode,
    evaluate_alert_check,
)
from products.alerts_platform.backend.facade.platform_metrics import (
    increment_checks,
    increment_checks_skipped,
    increment_state_transition,
    record_scheduler_lag,
    safe_record,
)

logger = structlog.get_logger(__name__)

INFLIGHT_KEY = "alerts:platform:insight:evaluations:inflight"

# Every query the parallel run sends starts with this, so its ClickHouse cost can be read apart from
# production's in `query_log`. Production's other tags are kept, so workload management treats both
# the same way.
QUERY_ID_PREFIX = "alerts-platform-insight:"

# The history row's error for a check ClickHouse refused for load. Stable, because a comparison
# matches on it to set those checks aside.
CAPACITY_REJECTED = "ClickHouse refused the query for capacity"

# Real-time and 15-minute alerts are the most expensive cadences and the ones production holds to a
# tighter budget, so the parallel run leaves them out until it agrees with production elsewhere.
EVALUATED_INTERVALS = frozenset(
    {
        AlertCalculationInterval.HOURLY,
        AlertCalculationInterval.DAILY,
        AlertCalculationInterval.WEEKLY,
        AlertCalculationInterval.MONTHLY,
    }
)


def is_evaluated_on_the_platform(alert: AlertConfiguration) -> bool:
    """Threshold alerts on an hourly or slower cadence. A detector alert makes its own decision,
    and the LLM detector makes a charged model call, so evaluating either in parallel costs twice."""
    return not alert.detector_config and alert.calculation_interval in EVALUATED_INTERVALS


def plan_insight_batch(team_id: int, slot: str, cutoff: datetime, *, expires_at: float) -> tuple[str, ...]:
    """Admits the batch's checks into the pool, in id order, while it has room, and returns the
    ids it admitted.

    The checks left out keep their due time, so a later tick finds them again. `expires_at` comes
    from the workflow rather than the clock, so a retried attempt gets back the same admitted ids.
    """
    checks = due_checks(team_id, SourceKind.INSIGHT.value, slot, cutoff)
    if not checks:
        return ()
    admitted = admit_evaluation_slots(
        [str(check.id) for check in checks],
        limit=settings.ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_EVALUATIONS,
        expires_at=expires_at,
        key=INFLIGHT_KEY,
    )
    if len(admitted) < len(checks):
        logger.info(
            "Deferred platform insight checks over the pool limit",
            team_id=team_id,
            slot=slot,
            admitted=len(admitted),
            deferred=len(checks) - len(admitted),
        )
    return tuple(admitted)


def evaluate_insight_check(
    team_id: int,
    slot: str,
    cutoff: datetime,
    configuration_id: str,
    *,
    held_until: float,
    evaluation_id: str,
) -> PlatformAlertOutcome | None:
    """Decides one admitted check, then frees its slot.

    Returns None when the configuration is no longer due, because an earlier attempt already
    recorded it or it was edited out of the batch. Writes nothing.
    """
    try:
        checks = due_checks(team_id, SourceKind.INSIGHT.value, slot, cutoff, configuration_ids=[configuration_id])
        if not checks:
            return None
        if checks[0].next_check_at is not None:
            # Wall clock rather than the tick: a check can wait in the pool and the worker queue,
            # and that wait is the lag a backlog shows up as.
            lag_ms = int((datetime.now(UTC) - checks[0].next_check_at).total_seconds() * 1000)
            if lag_ms > 0:
                safe_record(record_scheduler_lag, SourceKind.INSIGHT.value, lag_ms)
        return _decide(checks[0], cutoff, evaluation_id=evaluation_id)
    finally:
        release_evaluation_slot(configuration_id, held_until=held_until, key=INFLIGHT_KEY)


def _legacy_alert(check: PlatformAlertCheckInput) -> AlertConfiguration | None:
    if check.legacy_configuration_id is None:
        return None
    return (
        AlertConfiguration.objects.select_related("insight", "team", "threshold", "created_by")
        .filter(team_id=check.team_id, id=check.legacy_configuration_id)
        .first()
    )


def _snapshot(check: PlatformAlertCheckInput) -> AlertSnapshot:
    return insight_snapshot(
        AlertState(check.state), last_notified_at=check.last_notified_at, firing_started_at=check.firing_started_at
    )


def _evaluation_key(check: PlatformAlertCheckInput, cutoff: datetime) -> str:
    """The due slot. An insight check is one scheduled run, not a window, so the slot names it."""
    return f"slot:{slot_of(check.next_check_at, cutoff)}"


def _decide(check: PlatformAlertCheckInput, now: datetime, *, evaluation_id: str) -> PlatformAlertOutcome:
    snapshot = _snapshot(check)
    alert = _legacy_alert(check)
    if alert is None:
        # The production alert is gone, so this copy can never be compared again.
        return _skipped(check, snapshot, now=now, disable=True)
    if not alert.enabled or alert.insight.deleted or not is_evaluated_on_the_platform(alert):
        return _skipped(check, snapshot, now=now)
    if skip_because_of_weekend(alert) or is_utc_datetime_blocked(alert, now):
        return _skipped(check, snapshot, now=now)

    # Production gates evaluation on a snooze and holds the alert in SNOOZED, then clears it to
    # NOT_FIRING on the first check after the snooze ends. The legacy row is read for the snooze,
    # because a snooze set after the backfill copied the row lives only there.
    if alert.snoozed_until is not None and alert.snoozed_until > now:
        return _recorded(check, snapshot, apply_snooze(snapshot), now=now, skip=SkipReason.SOURCE_RULE)
    if snapshot.state == AlertState.SNOOZED:
        unsnoozed = apply_unsnooze(snapshot)
        snapshot = replace(snapshot, state=unsnoozed.new_state, consecutive_failures=unsnoozed.consecutive_failures)

    # Production's tags, so ClickHouse workload management treats the query the way it treats
    # production's and its cost is grouped the same way in the query log. The user is the
    # platform's own, so the parallel run never takes from production's per-user budget.
    tag_queries(
        ch_user=ClickHouseUser.ALERTS_PLATFORM_INSIGHT,
        team_id=alert.team_id,
        client_query_id=f"{QUERY_ID_PREFIX}{evaluation_id}",
        alert_config_id=str(alert.id),
        product=Product.PRODUCT_ANALYTICS,
        feature=Feature.ALERTING,
        alert_calculation_interval=alert.calculation_interval,
        alert_config_type=(alert.config or {}).get("type"),
    )
    started_at = time.monotonic()
    try:
        result = check_alert_for_insight(alert, evaluation_id=evaluation_id)
    except AlertExtractionError as error:
        return _recorded(
            check,
            snapshot,
            ControlPlaneOutcome(new_state=AlertState.ERRORED, consecutive_failures=0),
            now=now,
            notification=NotificationAction.ERROR,
            notified=True,
            error_message=str(error),
            skip=SkipReason.BROKEN_CONFIG,
            disable=True,
        )
    except Exception as error:
        if classify_query_error(error) == QueryErrorCategory.RATE_LIMITED:
            return _skipped(check, snapshot, now=now, skip=SkipReason.CAPACITY, error_message=CAPACITY_REJECTED)
        if not isinstance(error, CH_TRANSIENT_ERRORS):
            logger.exception("Platform insight check failed", check_id=str(check.id), error=str(error))
        return _verdict(
            check,
            snapshot,
            CheckInput(
                threshold_breached=False,
                error_message=str(error),
                is_transient_error=isinstance(error, CH_TRANSIENT_ERRORS),
            ),
            now=now,
            skip=SkipReason.QUERY_FAILED,
        )
    duration_ms = int((time.monotonic() - started_at) * 1000)

    if result.skipped_reason is not None:
        return _skipped(check, snapshot, now=now)
    return _verdict(
        check,
        snapshot,
        CheckInput(threshold_breached=bool(result.breaches)),
        now=now,
        value=result.value,
        query_duration_ms=duration_ms,
    )


def _verdict(
    check: PlatformAlertCheckInput,
    snapshot: AlertSnapshot,
    check_input: CheckInput,
    *,
    now: datetime,
    value: float | None = None,
    query_duration_ms: int | None = None,
    skip: SkipReason | None = None,
) -> PlatformAlertOutcome:
    outcome = evaluate_alert_check(snapshot, check_input, now, policy=INSIGHT_ALERT_POLICY)
    return _recorded(
        check,
        snapshot,
        outcome,
        now=now,
        notification=outcome.notification,
        notified=outcome.update_last_notified_at,
        value=value,
        error_message=outcome.error_message,
        query_duration_ms=query_duration_ms,
        skip=skip,
        disable=outcome.disable,
    )


def _skipped(
    check: PlatformAlertCheckInput,
    snapshot: AlertSnapshot,
    *,
    now: datetime,
    skip: SkipReason = SkipReason.SOURCE_RULE,
    error_message: str | None = None,
    disable: bool = False,
) -> PlatformAlertOutcome:
    """A check that reached no verdict. Recorded all the same, so its schedule advances."""
    unchanged = ControlPlaneOutcome(new_state=snapshot.state, consecutive_failures=snapshot.consecutive_failures)
    return _recorded(check, snapshot, unchanged, now=now, skip=skip, error_message=error_message, disable=disable)


def _recorded(
    check: PlatformAlertCheckInput,
    snapshot: AlertSnapshot,
    outcome: Outcome,
    *,
    now: datetime,
    notification: NotificationAction = NotificationAction.NONE,
    notified: bool = False,
    value: float | None = None,
    error_message: str | None = None,
    query_duration_ms: int | None = None,
    skip: SkipReason | None = None,
    disable: bool = False,
) -> PlatformAlertOutcome:
    """The one place an outcome is built. Every path goes through the firing decision, because
    an outcome without an episode clears the start of a firing the alert is still in."""
    source = SourceKind.INSIGHT.value
    safe_record(increment_checks, source, notification.value)
    if skip is not None:
        safe_record(increment_checks_skipped, source, skip.value)
    if check.state != outcome.new_state.value:
        safe_record(increment_state_transition, source, check.state, outcome.new_state.value)
    return PlatformAlertOutcome(
        configuration_id=check.id,
        evaluation_key=_evaluation_key(check, now),
        kind=NOTIFICATION_EVENT_KINDS[notification],
        new_state=outcome.new_state.value,
        notified=notified,
        consecutive_failures=outcome.consecutive_failures,
        firing_episode=decide_firing_episode(snapshot, outcome, now, policy=INSIGHT_ALERT_POLICY),
        value=value,
        error_message=error_message,
        query_duration_ms=query_duration_ms,
        disable=disable,
    )

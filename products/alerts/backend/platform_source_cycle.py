"""Evaluation of due insight alerts on the shared alerts platform.

A parallel run. The production insight fleet evaluates the same alerts against
`AlertConfiguration` and notifies their destinations. This decides what the platform would have
said, and asks for a delivery only for the alerts the platform owns.

Each platform row resolves to its production alert through `legacy_configuration_id`, because
`check_alert_for_insight` reads the insight, the threshold and the condition off that model. A row
with no production alert gets an unsaved one built from its own settings. The
query runs the way production runs it, and the verdict comes from the shared machine under
`insight_alert_policy`, applied to the platform's own state. `add_alert_check` is the production
writer, and nothing here calls it.

A check that production skips without a query is skipped here too, so both stacks answer the
same set of checks.
"""

import json
import time
import asyncio
from collections.abc import Callable, Collection, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from django.conf import settings

import structlog
from temporalio import activity

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, RateLimit
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.errors import CH_TRANSIENT_ERRORS, QueryErrorCategory, classify_query_error
from posthog.models.user import User
from posthog.query_cache.single_flight import skip_query_single_flight
from posthog.schema_enums import AlertCalculationInterval
from posthog.tasks.alerts.schedule_restriction import is_utc_datetime_blocked
from posthog.tasks.alerts.utils import (
    CHART_RENDER_TIMEOUT,
    AlertEvaluationResult,
    InsightChartRenderFailed,
    render_alert_insight_chart_or_raise,
    skip_because_of_weekend,
)
from posthog.temporal.alerts.admission import admit_evaluation_slots, release_evaluation_slot
from posthog.temporal.alerts.retry_policy import alert_timeouts

from products.alerts.backend.evaluation import check_alert_for_insight
from products.alerts.backend.evaluation.comparator import MAX_BREACH_MESSAGES
from products.alerts.backend.evaluation.contract import AlertDataUnavailableError, AlertExtractionError
from products.alerts.backend.evaluation.dispatcher import PerSeriesEvaluation, check_alert_per_series
from products.alerts.backend.facade.contracts import INSIGHT_EVENT_IDS_BY_INCIDENT_ACTION
from products.alerts.backend.insight_alert_state_machine import (
    INSIGHT_ALERT_POLICY,
    insight_alert_policy,
    insight_snapshot,
)
from products.alerts.backend.judge.contract import (
    LLM_DETECTOR_PAUSED_ERROR_CODE,
    LLM_DETECTOR_UNAVAILABLE_ERROR_CODE,
    LLM_DETECTOR_UNAVAILABLE_MESSAGE,
    LLMDetectorMisconfiguredError,
    LLMDetectorPausedError,
    LLMDetectorUnavailableError,
)
from products.alerts.backend.llm_detector_limits import is_llm_detector_config
from products.alerts.backend.logic.alert_email import INSIGHT_ALERT_ERRORED_EVENT_ID
from products.alerts.backend.logic.destinations import configured_destination_template_ids
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_alert_wording import insight_alert_url
from products.alerts.backend.platform_chart_detail import CHART_PENDING_KEY, RenderedChart
from products.alerts.backend.platform_firing_signal import with_firing_signal
from products.alerts.backend.platform_insight_alert import (
    RECURRENCE,
    evaluation_alert,
    insight_of,
    insight_row_settings,
    interval_of,
    investigated_alert,
)
from products.alerts.backend.platform_investigation import with_investigation
from products.alerts_platform.backend.facade.api import (
    destination_hears_kind,
    due_check_ids,
    due_checks,
    has_incident_destination,
    refresh_settings,
    slot_of,
)
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    AlertDeliveryRequest,
    AlertEventKind,
    DestinationType,
    GroupingMode,
    IncidentAction,
    InstanceCheckState,
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    PlatformAlertUpsert,
    SkipReason,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.facade.grouping import (
    GroupObservation,
    bounded_grouping_key,
    decide_groups,
    delivery_parts,
    not_breaching,
)
from products.alerts_platform.backend.facade.lifecycle import (
    NOTIFICATION_EVENT_KINDS,
    AlertPolicy,
    AlertSnapshot,
    AlertState,
    CheckInput,
    ControlPlaneOutcome,
    NotificationAction,
    Outcome,
    apply_snooze,
    apply_unsnooze,
    decide_firing_episode,
    decide_incident_action,
    evaluate_alert_check,
)
from products.alerts_platform.backend.facade.platform_metrics import (
    increment_checks,
    increment_checks_deferred,
    increment_checks_skipped,
    increment_state_transition,
    record_scheduler_lag,
    safe_record,
)
from products.alerts_platform.backend.facade.scheduling import validate_and_normalize_schedule_start_time
from products.cdp.backend.internal_events import LEGACY_INSIGHT_ALERT_EVENT

logger = structlog.get_logger(__name__)

# A member also locks its check, so a later run cannot start the same check while it runs.
INFLIGHT_KEY = "alerts:platform:insight:evaluations:inflight"
QUERY_INFLIGHT_KEY = "alerts:platform:insight:queries:inflight"
CHART_RENDER_INFLIGHT_KEY = "alerts:platform:insight:chart-renders:inflight"
# Under the one-minute tick, so a check that gave up is not still waiting when the next tick admits it.
QUERY_SLOT_WAIT_SECONDS = 45.0
QUERY_SLOT_POLL_SECONDS = 0.5
# Outlasts any query, so only a slot whose worker died expires before its release.
QUERY_SLOT_LEASE_SECONDS = int((alert_timeouts(None).evaluate_start_to_close + timedelta(minutes=2)).total_seconds())


class ClickHouseBudgetFull(Exception):
    """No ClickHouse slot came free in time. The check records nothing, so it stays due."""


# The size comes from the setting on each call, so the limit follows the live value.
_QUERY_LIMIT = RateLimit(
    max_concurrency=1,
    limit_name="alerts_platform_insight",
    get_task_name=lambda *_, **__: QUERY_INFLIGHT_KEY,
    get_task_id=lambda holder, **_: holder,
    ttl=QUERY_SLOT_LEASE_SECONDS,
    retry=QUERY_SLOT_POLL_SECONDS,
    retry_timeout=QUERY_SLOT_WAIT_SECONDS,
    retry_jitter=True,
    allow_team_bypass=False,
)


class ChartRenderPoolFull(Exception):
    """Every chart render slot is taken. The activity retries later, holding no worker slot meanwhile."""


class ChartRenderTimedOut(Exception):
    """The export ran out of time, so the firing goes out without its chart."""


# How many threads of the shared AI pool the parallel run may hold, so a stalled platform check
# never takes more than this from production. A thread counts until it ends, not until Temporal
# gives up on its attempt. Created per worker process and used only from the activity's event loop.
PLATFORM_LLM_CHECKS = asyncio.Semaphore(2)

# Every query the parallel run sends starts with this, so its ClickHouse cost can be read apart from
# production's in `query_log`. Production's other tags are kept, so workload management treats both
# the same way.
QUERY_ID_PREFIX = "alerts-platform-insight:"

# The history row's error for a check ClickHouse refused for load. Stable, because a comparison
# matches on it to set those checks aside.
CAPACITY_REJECTED = "ClickHouse refused the query for capacity"

# The detail key of the code that names a failed check's reason, as production keeps it on its check's error.
ERROR_CODE_KEY: Final = "error_code"

SLOT_KEY_PREFIX = "slot:"

EVALUATED_INTERVALS = frozenset(
    {
        AlertCalculationInterval.REAL_TIME,
        AlertCalculationInterval.EVERY_15_MINUTES,
        AlertCalculationInterval.HOURLY,
        AlertCalculationInterval.DAILY,
        AlertCalculationInterval.WEEKLY,
        AlertCalculationInterval.MONTHLY,
    }
)


# Which event each announced kind's destinations listen on. A resolve is left out, because
# production never announces one and the analytics platform team has not agreed to start. A kind
# with no event id reaches no destination.
_EVENT_IDS_BY_KIND: Final[dict[str, str]] = {
    AlertEventKind.FIRING.value: LEGACY_INSIGHT_ALERT_EVENT,
    AlertEventKind.ERRORED.value: INSIGHT_ALERT_ERRORED_EVENT_ID,
}
# Every event an insight alert's destinations can listen on, for a question about all of them.
DELIVERY_EVENT_IDS: Final = tuple(_EVENT_IDS_BY_KIND.values())


def is_evaluated_on_the_platform(alert: AlertConfiguration) -> bool:
    """Every alert production evaluates. An AI detector check makes a charged model call, so while
    both stacks run, each of those checks is paid for twice."""
    return alert.calculation_interval in EVALUATED_INTERVALS


# What an edit to an insight alert can change on its copy. The check refreshes these, and the due
# time follows from them, so it is left to the next advance. `take_ownership` changes the creator.
SETTINGS_FIELDS: Final = (
    "name",
    "source_config",
    "schedule_restriction",
    "check_interval_minutes",
    "recurrence_unit",
    "anchor_time",
    "created_by_id",
)


def platform_upsert_of(alert: AlertConfiguration) -> PlatformAlertUpsert | None:
    """The copy of one alert, or None when the platform does not evaluate it in parallel."""
    recurrence = RECURRENCE.get(alert.calculation_interval or "")
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
                "detector": alert.detector_config,
            },
            **insight_row_settings(alert),
        },
        check_interval_minutes=check_interval_minutes,
        recurrence_unit=recurrence_unit,
        anchor_time=alert.schedule_start_time,
        evaluation_periods=1,
        datapoints_to_alarm=1,
        cooldown_minutes=0,
        schedule_restriction=alert.schedule_restriction,
        next_check_at=alert.next_check_at,
        snooze_until=alert.snoozed_until,
        created_by_id=alert.created_by_id,
    )


def plan_insight_batch(
    team_id: int, slot: str, cutoff: datetime, *, expires_at: float, exclude: Collection[str] = ()
) -> tuple[str, ...]:
    """Admits the batch's checks into the pool, in id order, while it has room, and returns the
    ids it admitted.

    The checks left out keep their due time, so a later tick finds them again. `expires_at` comes
    from the workflow rather than the clock, so a retried attempt gets back the same admitted ids.

    `exclude` names the checks the workflow already started. A running check holds its slot under
    the same expiry, and a finished one stays due until the workflow records its outcome. Without
    `exclude`, a later round would admit either one again.
    """
    # The pool admits at most its size per round, so more candidates than that only add reads.
    candidates = due_check_ids(
        team_id,
        SourceKind.INSIGHT.value,
        slot,
        cutoff,
        exclude=exclude,
        limit=settings.ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_CHECKS,
    )
    if not candidates:
        return ()
    admitted = admit_evaluation_slots(
        list(candidates),
        limit=settings.ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_CHECKS,
        expires_at=expires_at,
        key=INFLIGHT_KEY,
    )
    # Only on a batch's first round, because later rounds of a full pool would repeat it every few seconds.
    if len(admitted) < len(candidates) and not exclude:
        logger.info(
            "Deferred platform insight checks over the pool limit",
            team_id=team_id,
            slot=slot,
            admitted=len(admitted),
            deferred=len(candidates) - len(admitted),
        )
        safe_record(increment_checks_deferred, SourceKind.INSIGHT.value, len(candidates) - len(admitted))
    return tuple(admitted)


def attempt_slot_token(held_until: float, attempt: int) -> float:
    """The expiry an attempt holds its slot under. Each attempt gets its own, so a timed-out attempt
    whose thread finishes late cannot release the slot its retry holds. The offset is negligible
    against the expiry itself."""
    return held_until + (attempt - 1) / 1000


def readmit_retried_check(
    team_id: int, configuration_id: str, *, previous_query_id: str, held_until: float, attempt: int
) -> float | None:
    """Prepares a retried check, and returns the slot token it holds, or None when the pool is full.

    A timed-out attempt's thread can still run its query, so the query is killed first, or the retry
    would run beside it. The retry then moves the slot to its own token, so the pool never counts
    the two attempts as one check that either can release.

    The earlier attempt keeps its ClickHouse slot. A kill can fail without an error, and a query that
    still runs must stay counted. Its thread frees the slot when the query ends, and the lease frees
    it if the worker died.
    """
    _stop_query(team_id, configuration_id, previous_query_id)
    release_evaluation_slot(configuration_id, held_until=attempt_slot_token(held_until, attempt - 1), key=INFLIGHT_KEY)
    token = attempt_slot_token(held_until, attempt)
    admitted = admit_evaluation_slots(
        [configuration_id],
        limit=settings.ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_CHECKS,
        expires_at=token,
        key=INFLIGHT_KEY,
    )
    return token if admitted else None


class ClickHouseQuerySlot:
    """Holds a ClickHouse slot around one attempt's query, and counts how long it waited for one.

    Raises `ClickHouseBudgetFull` when no slot comes free in time. `holder` names one attempt of one
    check, so a retry never takes over the slot of the attempt before it.
    """

    def __init__(self, holder: str, *, wait_seconds: float | None = None) -> None:
        self.holder = holder
        self.waited_ms = 0
        # A caller with a budget of its own waits no longer than it, on the same shared cap.
        self._limit = _QUERY_LIMIT if wait_seconds is None else replace(_QUERY_LIMIT, retry_timeout=wait_seconds)

    @contextmanager
    def __call__(self) -> Iterator[None]:
        waiting_since = time.monotonic()
        try:
            slot = self._limit.use(self.holder, limit=settings.ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_EVALUATIONS)
        except ConcurrencyLimitExceeded as error:
            raise ClickHouseBudgetFull() from error
        except Exception as error:
            # Redis is unreachable. The check stays due rather than recording a failure that is not the alert's.
            logger.exception("Could not take a ClickHouse slot for a platform insight check", holder=self.holder)
            raise ClickHouseBudgetFull() from error
        finally:
            self.waited_ms += int((time.monotonic() - waiting_since) * 1000)
        try:
            yield
        finally:
            if slot is not None:
                try:
                    self._limit.release(slot)
                except Exception:
                    # Best effort, so a Redis failure never replaces the query's result. The lease frees the slot.
                    logger.exception("Could not release a ClickHouse slot", holder=self.holder)


def _with_capacity_retries[T](run: Callable[[], T], alert: AlertConfiguration, query_slot: ClickHouseQuerySlot) -> T:
    """Runs a check's query, and runs it again after a ClickHouse refusal for load, on the retry
    policy production evaluates the alert's cadence with.

    Production raises the refusal and Temporal retries its activity. A parallel-run check has one
    attempt, so it retries inside that attempt instead, and keeps its evaluation slot between tries.
    The wait between tries counts as slot wait, so the recorded query duration leaves it out.
    """
    policy = alert_timeouts(alert.calculation_interval).evaluate_retry_policy
    delay = policy.initial_interval.total_seconds()
    # Temporal caps an unset maximum interval at 100 times the initial one.
    longest = (policy.maximum_interval or 100 * policy.initial_interval).total_seconds()
    tries = policy.maximum_attempts
    for tried in range(1, tries + 1):
        try:
            return run()
        except Exception as error:
            if (
                tried == tries
                or classify_query_error(error) != QueryErrorCategory.RATE_LIMITED
                or not _attempt_outlasts(delay)
            ):
                raise
            time.sleep(delay)
            query_slot.waited_ms += int(delay * 1000)
            if not _attempt_outlasts(0):
                raise
        delay = min(delay * policy.backoff_coefficient, longest)
    raise AssertionError("The retry loop returns or raises on its last try")


def _attempt_outlasts(seconds: float) -> bool:
    """Whether the Temporal attempt running this check is live and has `seconds` of its budget left.

    An attempt that timed out or was cancelled keeps its thread, and the failed-check cleanup has
    already stopped its queries, so a query it started after that would hold a ClickHouse slot that
    nothing frees. Outside an activity there is no budget to outlast.
    """
    if not activity.in_activity():
        return True
    if activity.is_cancelled():
        return False
    info = activity.info()
    # The attempt starts after it is scheduled, so its scheduled time gives a deadline no later than
    # the real one. Schedule-to-close counts from the first attempt, so it can end a retry sooner.
    deadlines = []
    if info.start_to_close_timeout is not None:
        deadlines.append(info.current_attempt_scheduled_time + info.start_to_close_timeout)
    if info.schedule_to_close_timeout is not None:
        deadlines.append(info.scheduled_time + info.schedule_to_close_timeout)
    return not deadlines or datetime.now(UTC) + timedelta(seconds=seconds) < min(deadlines)


def _stop_query(team_id: int, configuration_id: str, query_id: str) -> None:
    # Imported here: at module level it changes how many queries the access-control tests count.
    from posthog.clickhouse.cancel import cancel_query_on_cluster  # noqa: PLC0415

    try:
        cancel_query_on_cluster(team_id, f"{QUERY_ID_PREFIX}{query_id}")
    except Exception:
        logger.exception("Could not stop a timed-out platform insight check", configuration_id=configuration_id)


def legacy_alerts_of(
    team_id: int, slot: str, cutoff: datetime, configuration_ids: Collection[str]
) -> dict[str, AlertConfiguration]:
    """The alert behind each due check, keyed by the check's id, with what planning reads: its
    cadence, detector and owner. A copy's comes from its insight row, and an alert insight keeps no
    row for gets an unsaved one built from the platform alert."""
    if not configuration_ids:
        return {}
    checks = due_checks(team_id, SourceKind.INSIGHT.value, slot, cutoff, configuration_ids=list(configuration_ids))
    legacy_ids = {
        check.legacy_configuration_id: str(check.id) for check in checks if check.legacy_configuration_id is not None
    }
    alerts = AlertConfiguration.objects.filter(team_id=team_id, id__in=list(legacy_ids)).only(
        "id", "calculation_interval", "detector_config", "owner"
    )
    planned = {legacy_ids[alert.id]: alert for alert in alerts}
    for check in checks:
        if check.legacy_configuration_id is None:
            planned[str(check.id)] = AlertConfiguration(
                id=check.id,
                team_id=team_id,
                calculation_interval=interval_of(check.check_interval_minutes),
                detector_config=(check.source_config.get(SOURCE_CONDITION_KEY) or {}).get("detector"),
                owner=PlatformAlertOwner.PLATFORM,
            )
    return planned


def evaluate_insight_check(
    team_id: int,
    slot: str,
    cutoff: datetime,
    configuration_id: str,
    *,
    held_until: float,
    evaluation_id: str,
    attempt: int = 1,
    final_attempt: bool = True,
    uses_llm_detector: bool = False,
) -> SourceBatchEvaluation | None:
    """Decides one admitted check, then frees its slot.

    Returns the outcome with its delivery, if it asks for one. Returns None when the configuration
    is no longer due, because an earlier attempt already recorded it or it was edited out of the
    batch, when its detector no longer matches the worker it was routed to, or when no ClickHouse
    slot came free in time. Writes nothing.

    `evaluation_id` names the check across its attempts, so the AI detector reuses a verdict an
    earlier attempt paid for. An AI detector that reaches no verdict raises
    `LLMDetectorUnavailableError` for a retry, and keeps the slot for it, unless `final_attempt`.
    """
    retrying = False
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
        try:
            # Other ClickHouse users, production's included, run this query in flights of their own but write
            # the same cache entry, so a platform follower can find their entry in place of its leader's.
            with skip_query_single_flight():
                outcome = _decide(
                    checks[0],
                    cutoff,
                    evaluation_id=evaluation_id,
                    attempt=attempt,
                    final_attempt=final_attempt,
                    uses_llm_detector=uses_llm_detector,
                )
        except LLMDetectorUnavailableError:
            retrying = True
            raise
        if outcome is None:
            return None
        evaluation = _evaluation(checks[0], outcome)
    finally:
        if not retrying:
            release_evaluation_slot(configuration_id, held_until=held_until, key=INFLIGHT_KEY)
    # After the slot is free, because the investigation's reads need no ClickHouse slot.
    try:
        evaluation = with_investigation(checks[0], evaluation)
    except Exception:
        # The firing still goes out, uninvestigated, rather than the check being lost as errored.
        logger.exception("Failed to decide a platform insight firing's investigation", check_id=configuration_id)
    try:
        return with_firing_signal(checks[0], evaluation)
    except Exception:
        # The signal is best effort, so the firing goes out without one.
        logger.exception("Failed to decide a platform insight firing's signal", check_id=configuration_id)
        return evaluation


def fail_insight_check(
    team_id: int,
    slot: str,
    cutoff: datetime,
    configuration_id: str,
    *,
    error_message: str,
    error_type: str | None = None,
) -> SourceBatchEvaluation | None:
    """The errored outcome of a check whose every attempt ended without one, such as a query that ran
    past its time budget, as production records an errored check when its retries run out.

    `error_type` names the class of the last attempt's error, as production reads it to word a
    judge that could not be reached.
    Returns None when the check is no longer due, or its production alert is gone or switched off.
    Writes no state.
    """
    checks = due_checks(team_id, SourceKind.INSIGHT.value, slot, cutoff, configuration_ids=[configuration_id])
    if not checks:
        return None
    alert = evaluation_alert(checks[0])
    # As production: switching an alert off mid-check is not a failure of the alert.
    if alert is None or not alert.enabled:
        return None
    if error_type == LLMDetectorUnavailableError.__name__:
        # As production: the raw transport error is not the owner's configuration, so it gets its own wording.
        error_message = LLM_DETECTOR_UNAVAILABLE_MESSAGE
    outcome = _verdict(
        checks[0],
        _snapshot(checks[0]),
        CheckInput(threshold_breached=False, error_message=error_message),
        now=cutoff,
        skip=SkipReason.QUERY_FAILED,
        context=_context(alert),
    )
    return _evaluation(checks[0], outcome)


def stop_insight_queries(team_id: int, configuration_id: str, query_ids: Sequence[str]) -> None:
    """Stops the queries a failed check's attempts may still run. A timed-out attempt's thread
    keeps its query going, and nothing else stops it."""
    for query_id in query_ids:
        _stop_query(team_id, configuration_id, query_id)


def _evaluation(check: PlatformAlertCheckInput, outcome: PlatformAlertOutcome) -> SourceBatchEvaluation:
    if check.legacy_configuration_id is not None:
        # Production times each check by its own alert's id, so the copy checks at that minute.
        outcome = replace(outcome, schedule_key=str(check.legacy_configuration_id))
    delivery = _delivery(check, outcome)
    return SourceBatchEvaluation(outcomes=(outcome,), deliveries=(delivery,) if delivery is not None else ())


def _delivery(check: PlatformAlertCheckInput, outcome: PlatformAlertOutcome) -> AlertDeliveryRequest | None:
    """The delivery for a recorded outcome, or None when it neither announces nor moves a firing.

    A firing that opens or closes needs a delivery even though no resolve is announced, because a
    paging destination needs one resolve for every trigger. An alert with no such destination gets
    no incident action, so its edges start no delivery.
    """
    # A source-owned alert is the insight stack's to send.
    if not check.owned_by_platform:
        return None
    alert_id = str(check.destination_alert_id)
    kinds = [group.kind for group in outcome.groups]
    if outcome.failure is not None:
        kinds.append(outcome.failure.kind)
    sends_messages = any(kind.value in _EVENT_IDS_BY_KIND for kind in kinds)
    actions = _incident_actions(check, outcome)
    if actions and not _has_incident_destination(check):
        actions = {}
    if not sends_messages and not actions:
        return None
    return AlertDeliveryRequest(
        source=SourceKind.INSIGHT,
        team_id=check.team_id,
        configuration_id=str(check.id),
        # The recorded key unchanged, so the delivery addresses the row this check wrote.
        evaluation_key=outcome.evaluation_key,
        destination_alert_id=alert_id,
        event_ids_by_kind=_EVENT_IDS_BY_KIND,
        event_ids_by_incident_action=INSIGHT_EVENT_IDS_BY_INCIDENT_ACTION,
        incident_actions=actions,
        sends_messages=sends_messages,
        source_alert_url=_alert_url(check, alert_id),
        owned_by_platform=True,
        overflowed=outcome.overflowed,
        overflow_is_lower_bound=outcome.overflow_is_lower_bound,
        parts=delivery_parts(outcome, actions),
    )


def _has_incident_destination(check: PlatformAlertCheckInput) -> bool:
    """Whether a destination of this alert follows the incident events, as a HogFunction or as a
    destination the platform keeps. Read only on a firing edge. It decides only that the edge starts a
    delivery: which destinations that delivery reaches is the delivery's to decide."""
    if configured_destination_template_ids(
        team_id=check.team_id,
        alert_id=str(check.destination_alert_id),
        allowed_event_ids=tuple(INSIGHT_EVENT_IDS_BY_INCIDENT_ACTION.values()),
    ):
        return True
    return has_incident_destination(team_id=check.team_id, configuration_id=check.id)


def _incident_actions(check: PlatformAlertCheckInput, outcome: PlatformAlertOutcome) -> dict[str, IncidentAction]:
    """Whether each group's firing opened or closed, read from the states rather than the announcement.

    A failed check moves no instance, so its incident stays open with its firing. Closing it would
    leave a re-enabled alert that still breaches firing with no incident.
    """
    policy = _policy(check) if check.grouping.mode == GroupingMode.SINGLE else GROUPED_INSIGHT_ALERT_POLICY
    return {
        group.grouping_key: action
        for group in outcome.groups
        if (
            action := decide_incident_action(
                AlertState(check.instance(group.grouping_key).state), AlertState(group.new_state), policy=policy
            )
        )
        is not None
    }


def _alert_url(check: PlatformAlertCheckInput, alert_id: str) -> str | None:
    """The alert's page on its insight, so a native message links where the insight stack's does."""
    insight = insight_of(check.team_id, check.source_config)
    return insight_alert_url(check.team_id, insight.short_id, alert_id) if insight is not None else None


def _snapshot(
    check: PlatformAlertCheckInput,
    instance: InstanceCheckState | None = None,
    *,
    snooze_until: datetime | None = None,
) -> AlertSnapshot:
    instance = instance or check.instance()
    return insight_snapshot(
        AlertState(instance.state),
        last_notified_at=instance.last_notified_at,
        firing_started_at=instance.firing_started_at,
        snooze_until=snooze_until,
    )


def _policy(check: PlatformAlertCheckInput) -> AlertPolicy:
    """The policy production runs for the alert, read from the detector the copy stores."""
    return insight_alert_policy(check.condition.get("detector"))


def _evaluation_key(check: PlatformAlertCheckInput, cutoff: datetime) -> str:
    """The due slot. An insight check is one scheduled run, not a window, so the slot names it."""
    return evaluation_key_for_slot(slot_of(check.next_check_at, cutoff))


def evaluation_key_for_slot(slot: str) -> str:
    return f"{SLOT_KEY_PREFIX}{slot}"


def slot_of_evaluation_key(evaluation_key: str) -> datetime | None:
    """The due slot a key names, or None for another shape. Kept beside the minter, so a change to
    one breaks the other's tests rather than the comparison silently."""
    if not evaluation_key.startswith(SLOT_KEY_PREFIX):
        return None
    try:
        return datetime.fromisoformat(evaluation_key.removeprefix(SLOT_KEY_PREFIX))
    except ValueError:
        return None


def _decide(
    check: PlatformAlertCheckInput,
    now: datetime,
    *,
    evaluation_id: str,
    attempt: int,
    final_attempt: bool,
    uses_llm_detector: bool,
) -> PlatformAlertOutcome | None:
    snapshot = _snapshot(check)
    alert = evaluation_alert(check)
    if alert is None:
        # The production alert or the insight is gone, so this alert can never be checked again.
        return _skipped(check, snapshot, now=now, disable=True)
    if _ai_detector_not_copied(check, alert):
        # Before the refresh, which would write the AI detector onto the copy and opt it in. The
        # copy is switched off, because it would otherwise skip on its stale schedule every tick.
        return _skipped(check, snapshot, now=now, disable=True)
    if check.legacy_configuration_id is not None:
        # Before any skip, because a skip advances the check by the copy's schedule.
        check = _following(check, alert)
    if not alert.enabled or alert.insight.deleted or not is_evaluated_on_the_platform(alert):
        return _skipped(check, snapshot, now=now)
    # As production: a plan that lost a cadence stops the alert, because the API checks it only on a write.
    entitlement_error = AlertConfiguration.interval_entitlement_error(
        calculation_interval=alert.calculation_interval, organization=alert.team.organization
    )
    if entitlement_error:
        return _broken(check, snapshot, alert, now=now, message=entitlement_error)
    if skip_because_of_weekend(alert) or is_utc_datetime_blocked(alert, now):
        return _skipped(check, snapshot, now=now)
    if is_llm_detector_config(alert.detector_config) != uses_llm_detector:
        # As production: an edit since the plan means this worker may not hold the model
        # credentials. No outcome keeps the check due, so the next tick plans and routes it again.
        return None

    # Production gates evaluation on a snooze and holds the alert in SNOOZED, then clears it to
    # NOT_FIRING on the first check after the snooze ends. The legacy row is read for the snooze,
    # because a snooze set after the backfill copied the row lives only there.
    if alert.snoozed_until is not None and alert.snoozed_until > now:
        return _recorded(check, snapshot, apply_snooze(snapshot), now=now, skip=SkipReason.SOURCE_RULE)
    if snapshot.state == AlertState.SNOOZED:
        unsnoozed = apply_unsnooze(snapshot)
        snapshot = replace(snapshot, state=unsnoozed.new_state, consecutive_failures=unsnoozed.consecutive_failures)

    _run_as_copy_creator(check, alert)
    # Production's tags, so ClickHouse workload management treats the query the way it treats
    # production's and its cost is grouped the same way in the query log. The user is the
    # platform's own, so the parallel run never takes from production's per-user budget.
    tag_queries(
        ch_user=ClickHouseUser.ALERTS_PLATFORM_INSIGHT,
        team_id=alert.team_id,
        client_query_id=f"{QUERY_ID_PREFIX}{evaluation_id}:{attempt}",
        alert_config_id=str(alert.id),
        product=Product.PRODUCT_ANALYTICS,
        feature=Feature.ALERTING,
        alert_calculation_interval=alert.calculation_interval,
        alert_config_type=(alert.config or {}).get("type"),
    )
    query_slot = ClickHouseQuerySlot(f"{evaluation_id}:{attempt}")
    if check.grouping.mode != GroupingMode.SINGLE:
        return _decide_grouped(check, snapshot, alert, now=now, query_slot=query_slot)
    started_at = time.monotonic()
    try:
        result = _with_capacity_retries(
            lambda: check_alert_for_insight(alert, evaluation_id=evaluation_id, query_slot=query_slot),
            alert,
            query_slot,
        )
    except ClickHouseBudgetFull:
        return None
    except LLMDetectorUnavailableError:
        if not final_attempt:
            # As production: a judge that reached no verdict gets another attempt, and only the
            # last one records the failure.
            raise
        return _verdict(
            check,
            snapshot,
            CheckInput(threshold_breached=False, error_message=LLM_DETECTOR_UNAVAILABLE_MESSAGE),
            now=now,
            skip=SkipReason.QUERY_FAILED,
            context=_context(alert),
            # History shows this reason by its code, and an errored check that repeats announces nothing.
            check_detail={ERROR_CODE_KEY: LLM_DETECTOR_UNAVAILABLE_ERROR_CODE},
        )
    except LLMDetectorPausedError as error:
        # As production: no retry, and the alert stays enabled so it resumes once access or credits return.
        return _errored_stays_enabled(
            check,
            snapshot,
            alert,
            now=now,
            message=str(error),
            check_detail={ERROR_CODE_KEY: LLM_DETECTOR_PAUSED_ERROR_CODE},
        )
    except AlertDataUnavailableError as error:
        return _errored_stays_enabled(check, snapshot, alert, now=now, message=str(error))
    except (AlertExtractionError, LLMDetectorMisconfiguredError) as error:
        return _broken(check, snapshot, alert, now=now, message=str(error))
    except Exception as error:
        return _query_failed(check, snapshot, alert, error, now=now)
    duration_ms = int((time.monotonic() - started_at) * 1000) - query_slot.waited_ms

    if result.skipped_reason is not None:
        return _skipped(check, snapshot, now=now)
    return _verdict(
        check,
        snapshot,
        CheckInput(threshold_breached=bool(result.breaches)),
        now=now,
        value=result.value,
        query_duration_ms=duration_ms,
        firing=(alert, result.breaches or []),
        check_detail=detector_detail(result) if alert.detector_config else None,
        breach_details=(result.triggered_metadata or {}).get("breach_details"),
    )


def _ai_detector_not_copied(check: PlatformAlertCheckInput, alert: AlertConfiguration) -> bool:
    """Whether a parallel-run copy made without the AI detector would now run one.

    A check reads the alert's live detector, so an alert switched to the AI detector after the
    backfill copied it would make a model call the project pays for twice. The backfill copies
    AI detector alerts only on request, and a copy it made that way stores the AI detector.
    """
    if check.owned_by_platform or not is_llm_detector_config(alert.detector_config):
        return False
    return not is_llm_detector_config(check.condition.get("detector"))


def _run_as_copy_creator(check: PlatformAlertCheckInput, alert: AlertConfiguration) -> None:
    """Makes the creator the copy records the user the check's queries run as. A copy the creator
    backfill has not reached records none, and one whose user is gone records an id that loads no
    one. Both keep the alert row's, because a check with no user disables the alert."""
    if check.created_by_id is None or check.created_by_id == alert.created_by_id:
        return
    if creator := User.objects.filter(id=check.created_by_id).first():
        alert.created_by = creator


def _following(check: PlatformAlertCheckInput, alert: AlertConfiguration) -> PlatformAlertCheckInput:
    """The check with its alert's settings as they are now, written back to the copy first.

    An edit to the alert never reaches the copy otherwise, so history and messages would quote an
    old name or condition, and the copy would keep its old cadence until the next backfill.
    """
    upsert = platform_upsert_of(alert)
    if upsert is None:
        return check
    try:
        # The copy stores the anchor normalized, so the alert's start time is compared in that form.
        upsert = replace(upsert, anchor_time=validate_and_normalize_schedule_start_time(upsert.anchor_time))
    except ValueError:
        # The backfill skips an alert whose start time cannot be read, so the copy keeps its own.
        return check
    if all(getattr(check, field) == getattr(upsert, field) for field in SETTINGS_FIELDS):
        return check
    try:
        refresh_settings(check.team_id, check.id, upsert)
    except Exception:
        # History records the stored copy, so the check evaluates that copy and stays true to it.
        logger.exception("Failed to bring a platform insight copy up to date", check_id=str(check.id))
        return check
    return replace(check, **{field: getattr(upsert, field) for field in SETTINGS_FIELDS})


def _broken(
    check: PlatformAlertCheckInput, snapshot: AlertSnapshot, alert: AlertConfiguration, *, now: datetime, message: str
) -> PlatformAlertOutcome:
    """An alert production cannot evaluate as configured. It errors and is disabled, as production does."""
    return _recorded(
        check,
        snapshot,
        ControlPlaneOutcome(new_state=AlertState.ERRORED, consecutive_failures=0),
        now=now,
        notification=NotificationAction.ERROR,
        notified=True,
        error_message=message,
        skip=SkipReason.BROKEN_CONFIG,
        disable=True,
        source_detail=_context(alert),
    )


def _errored_stays_enabled(
    check: PlatformAlertCheckInput,
    snapshot: AlertSnapshot,
    alert: AlertConfiguration,
    *,
    now: datetime,
    message: str,
    check_detail: dict[str, Any] | None = None,
) -> PlatformAlertOutcome:
    """A check that reached no verdict, but that a later check can, such as one whose history is still short.

    As production, it errors and the copy stays enabled. `AlertDataUnavailableError` subclasses
    `AlertExtractionError`, so its catch must come before the one that sends the copy to `_broken`.
    """
    return _verdict(
        check,
        snapshot,
        CheckInput(threshold_breached=False, error_message=message),
        now=now,
        skip=SkipReason.QUERY_FAILED,
        context=_context(alert),
        check_detail=check_detail,
    )


def _query_failed(
    check: PlatformAlertCheckInput,
    snapshot: AlertSnapshot,
    alert: AlertConfiguration,
    error: Exception,
    *,
    now: datetime,
) -> PlatformAlertOutcome:
    """A query that did not finish. A refusal for load is a skip; anything else is a failed check."""
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
        context=_context(alert),
    )


# Skips that mean the check could not evaluate, as opposed to a check the source chose not to run.
_FAILED_CHECKS: Final = frozenset({SkipReason.QUERY_FAILED, SkipReason.BROKEN_CONFIG})

# The one label a grouped insight alert splits on: each breakdown value is a group.
BREAKDOWN_GROUPING_KEY = "breakdown"

# How much of what a check found one group's detail keeps. Production lists one breach per series,
# and every group's detail rides in the outcome Temporal carries, so a long label must not grow it.
MAX_DETAIL_BREACHES: Final = 10
MAX_BREACH_CHARS: Final = 500
MAX_DETAIL_ROWS: Final = MAX_BREACH_MESSAGES
MAX_TAGS: Final = 10
MAX_TAG_CHARS: Final = 100
# A breakdown alert announces up to `max_instances` groups in one outcome, and each group repeats
# the card fields. Per-group caps bound one group, not their sum, so the sum is bounded here: once
# a grouped evaluation has spent this much on detail, the groups after it keep only the fields the
# message cannot be built without. Well under Temporal's payload limit, which the outcome shares
# with the rest of the verdicts.
MAX_TOTAL_DETAIL_CHARS: Final = 200_000

# A breakdown value can be muted on its own, which production cannot express, so the platform's
# mute applies: the value is still judged and only its announcement is held. A snooze of the
# production alert never reaches here, because `_decide` records that check without a query.
# Built on the statistical policy alone, because the AI detector is refused on a breakdown insight.
GROUPED_INSIGHT_ALERT_POLICY: Final = replace(INSIGHT_ALERT_POLICY, mute_gates_notification_only=True)


def _decide_grouped(
    check: PlatformAlertCheckInput,
    snapshot: AlertSnapshot,
    alert: AlertConfiguration,
    *,
    now: datetime,
    query_slot: ClickHouseQuerySlot,
) -> PlatformAlertOutcome | None:
    """One check of a breakdown alert, judged per breakdown value through the platform's decision.

    An open value the query no longer returns is judged as not breaching, so it can resolve. When
    the breakdown limit folded values into "Other", a missing value may still breach, so an open
    value the query did not return is left as it is.
    """
    if tuple(check.grouping.keys) != (BREAKDOWN_GROUPING_KEY,):
        return _broken(
            check, snapshot, alert, now=now, message=f"An insight alert can only group by {BREAKDOWN_GROUPING_KEY}"
        )
    started_at = time.monotonic()
    try:
        evaluated = _with_capacity_retries(
            lambda: check_alert_per_series(alert, query_slot=query_slot), alert, query_slot
        )
    except ClickHouseBudgetFull:
        return None
    except AlertDataUnavailableError as error:
        return _errored_stays_enabled(check, snapshot, alert, now=now, message=str(error))
    except AlertExtractionError as error:
        return _broken(check, snapshot, alert, now=now, message=str(error))
    except Exception as error:
        return _query_failed(check, snapshot, alert, error, now=now)
    if not isinstance(evaluated, PerSeriesEvaluation):
        return _skipped(check, snapshot, now=now)
    duration_ms = int((time.monotonic() - started_at) * 1000) - query_slot.waited_ms

    decision = decide_groups(
        check,
        [
            GroupObservation(
                grouping_key=bounded_grouping_key(series.identity),
                current_breached=bool(series.result.breaches),
                value=series.result.value,
                labels={BREAKDOWN_GROUPING_KEY: series.label},
            )
            for series in evaluated.series
        ],
        snapshot_of=lambda instance, _prior: _snapshot(check, instance, snooze_until=instance.snooze_until),
        policy=GROUPED_INSIGHT_ALERT_POLICY,
        now=now,
        absent=(lambda _key: None) if evaluated.truncated else not_breaching,
    )
    for verdict in decision.verdicts:
        _record_metrics(verdict.outcome.notification, verdict.snapshot.state.value, verdict.group.new_state)
    if any(verdict.outcome.notification == NotificationAction.FIRE for verdict in decision.verdicts):
        # The row `decide_groups` judged for each key: the first, unless a later one breaches and it did not.
        breaches: dict[str, list[str]] = {}
        details_by_key: dict[str, list[dict[str, str]]] = {}
        for series in evaluated.series:
            key, found = bounded_grouping_key(series.identity), series.result.breaches or []
            if key not in breaches or (found and not breaches[key]):
                breaches[key] = found
                details_by_key[key] = (series.result.triggered_metadata or {}).get("breach_details", [])
        wants_chart = _wants_chart(check, alert)
        # One insight, so its tags are read once rather than once per firing breakdown value.
        tags = _insight_tags(alert)
        budget = _DetailBudget()
        verdicts = []
        for verdict in decision.verdicts:
            if verdict.outcome.notification != NotificationAction.FIRE:
                verdicts.append(verdict)
                continue
            key = verdict.group.grouping_key
            full = budget.allows()
            detail = _detail(
                alert,
                breaches.get(key, []),
                wants_chart=wants_chart,
                breach_details=details_by_key.get(key) if full else None,
                tags=tags if full else [],
            )
            budget.charge(detail)
            verdicts.append(replace(verdict, group=replace(verdict.group, source_detail=detail)))
        decision = replace(decision, verdicts=tuple(verdicts))
    return decision.as_outcome(
        configuration_id=check.id,
        evaluation_key=_evaluation_key(check, now),
        grouping=check.grouping,
        query_duration_ms=duration_ms,
        results_cut=evaluated.truncated,
    )


def _firing_detail(
    check: PlatformAlertCheckInput,
    alert: AlertConfiguration,
    breaches: Sequence[str],
    *,
    breach_details: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """What production's `$insight_alert_firing` carries beside the verdict, which only the check can know."""
    return _detail(alert, breaches, wants_chart=_wants_chart(check, alert), breach_details=breach_details)


def _wants_chart(check: PlatformAlertCheckInput, alert: AlertConfiguration) -> bool:
    # A render takes up to a minute and a half, so only an alert the platform delivers for pays
    # for one. Production renders no chart for a real-time alert either.
    return check.owned_by_platform and alert.calculation_interval != AlertCalculationInterval.REAL_TIME


def render_firing_chart(team_id: int, alert_id: str, *, held_until: float) -> RenderedChart | None:
    """Render the chart a firing of this alert sends, or None when none applies.

    The evaluation workflow calls this after the check, so the render never holds the check's slot.
    Raises `ChartRenderPoolFull` when the render pool has no room, `ChartRenderTimedOut` when the
    export used its whole time limit and returned nothing, and `InsightChartRenderFailed` when the
    render fails otherwise.
    """
    if not admit_evaluation_slots(
        [alert_id],
        limit=settings.ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_CHART_RENDERS,
        expires_at=held_until,
        key=CHART_RENDER_INFLIGHT_KEY,
    ):
        raise ChartRenderPoolFull()
    try:
        # The id a firing names its chart by, which is the platform alert's own for an alert with no insight row.
        alert = investigated_alert(team_id, UUID(alert_id))
        if alert is None:
            return None
        started = time.monotonic()
        try:
            chart = render_alert_insight_chart_or_raise(
                alert,
                # Destinations the platform keeps are keyed by its own id, which only a built alert carries.
                platform_slack_destination=alert._state.adding
                and destination_hears_kind(
                    team_id=team_id,
                    configuration_id=alert.id,
                    destination_type=DestinationType.SLACK,
                    event_kind=AlertEventKind.FIRING,
                ),
            )
        except InsightChartRenderFailed as error:
            # A timed-out export fails like any other, so only its duration tells the two apart.
            if time.monotonic() - started >= CHART_RENDER_TIMEOUT.total_seconds():
                raise ChartRenderTimedOut() from error
            raise
        return (
            RenderedChart(asset_id=chart.asset_id, render_user_id=chart.render_user_id) if chart is not None else None
        )
    finally:
        release_evaluation_slot(alert_id, held_until=held_until, key=CHART_RENDER_INFLIGHT_KEY)


def _context(alert: AlertConfiguration) -> dict[str, Any]:
    """The insight a message names and links to, which every message about the alert carries."""
    return {"insight_name": alert.insight.name, "insight_short_id": alert.insight.short_id}


def _clipped(text: str, limit: int = MAX_BREACH_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _insight_interval(alert: AlertConfiguration) -> str | None:
    """The insight's own interval, read the way production reads it.

    A stored query can carry an explicit `"source": null`, which a `.get` default never replaces,
    so the source is bound first and checked. This runs on the firing path, where an `AttributeError`
    would cost the check rather than the label.
    """
    query = alert.insight.query if isinstance(alert.insight.query, dict) else {}
    source = query.get("source")
    return (source if isinstance(source, dict) else query).get("interval")


class _DetailBudget:
    """Keeps one grouped evaluation's details inside `MAX_TOTAL_DETAIL_CHARS` in total.

    Each group is built in full while the budget holds. After it runs out the rest are built
    without the repeated fields, so a wide breakdown announces every group it fired on rather than
    losing the whole outcome to a payload the activity cannot carry.
    """

    def __init__(self) -> None:
        self._spent = 0

    def allows(self) -> bool:
        return self._spent < MAX_TOTAL_DETAIL_CHARS

    def charge(self, detail: dict[str, Any]) -> None:
        self._spent += len(json.dumps(detail, default=str))


def _insight_tags(alert: AlertConfiguration) -> list[str]:
    # Sorted and sliced in Python so the prefetch on `legacy_alert` is used. A `filter()` here
    # would build a new queryset and go back to the database for every firing.
    names = sorted(item.tag.name for item in alert.insight.tagged_items.all() if item.tag.team_id == alert.team_id)
    return [_clipped(name, MAX_TAG_CHARS) for name in names[:MAX_TAGS]]


def _detail(
    alert: AlertConfiguration,
    breaches: Sequence[str],
    *,
    wants_chart: bool,
    breach_details: list[dict[str, str]] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    # Bounded, because the outcome crosses into Temporal and a breach names user-written labels.
    detail: dict[str, Any] = {
        "breaches": [_clipped(breach) for breach in breaches[:MAX_DETAIL_BREACHES]],
        **_context(alert),
        # The legacy alert's id, which a native message's snooze menu snoozes.
        "alert_id": str(alert.id),
        # Recorded now so the Slack card is a function of the transition and a later rename or delete cannot change it.
        "metric_name": _clipped(alert.insight.name or alert.insight.derived_name or "Insight", MAX_TAG_CHARS),
        "timezone": alert.team.timezone,
        "is_anomaly": bool(alert.detector_config),
        "insight_interval": _insight_interval(alert),
        "tags": _insight_tags(alert) if tags is None else tags,
        "team_name": _clipped(alert.team.name, MAX_TAG_CHARS),
    }
    if breach_details:
        detail["breach_details"] = [
            {key: _clipped(str(value)) for key, value in row.items()} for row in breach_details[:MAX_DETAIL_ROWS]
        ]
    if wants_chart:
        detail[CHART_PENDING_KEY] = str(alert.id)
    return detail


# A scheduled check scores only its latest point, so a detector reports one score and at most one
# fired point. These bound a detector that reports more, because every check's detail rides in the
# outcome Temporal carries.
MAX_DETECTOR_POINTS: Final = 10
MAX_RATIONALE_CHARS: Final = 1000


def detector_detail(result: AlertEvaluationResult) -> dict[str, Any]:
    """What production keeps on a detector check beside its verdict, under the same names: the
    score, kind and reason history shows, and the fired points the insight chart marks.

    Kept on every detector check, not only on one that sends, because production shows them on every check.
    """
    detail: dict[str, Any] = {
        "anomaly_scores": (result.anomaly_scores or [])[-MAX_DETECTOR_POINTS:],
        "triggered_points": (result.triggered_points or [])[-MAX_DETECTOR_POINTS:],
        "triggered_dates": (result.triggered_dates or [])[-MAX_DETECTOR_POINTS:],
        "interval": result.interval,
        "triggered_metadata": dict(result.triggered_metadata or {}),
    }
    rationale = detail["triggered_metadata"].get("rationale")
    if isinstance(rationale, str):
        detail["triggered_metadata"]["rationale"] = _clipped(rationale, MAX_RATIONALE_CHARS)
    # Empty values are left out, so a reader finds `triggered_dates` only on a check that fired on a point.
    return {key: value for key, value in detail.items() if value}


def _verdict(
    check: PlatformAlertCheckInput,
    snapshot: AlertSnapshot,
    check_input: CheckInput,
    *,
    now: datetime,
    value: float | None = None,
    query_duration_ms: int | None = None,
    skip: SkipReason | None = None,
    firing: tuple[AlertConfiguration, Sequence[str]] | None = None,
    breach_details: list[dict[str, str]] | None = None,
    context: dict[str, Any] | None = None,
    check_detail: dict[str, Any] | None = None,
) -> PlatformAlertOutcome:
    outcome = evaluate_alert_check(snapshot, check_input, now, policy=_policy(check))
    source_detail: dict[str, Any] | None
    if firing is not None and outcome.notification == NotificationAction.FIRE:
        source_detail = _firing_detail(check, *firing, breach_details=breach_details)
    elif outcome.notification != NotificationAction.NONE:
        source_detail = context
    else:
        source_detail = None
    # Kept on every check, including one that announces nothing.
    if check_detail:
        source_detail = {**(source_detail or {}), **check_detail}
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
        source_detail=source_detail,
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


def _record_metrics(
    notification: NotificationAction, previous_state: str, new_state: str, *, skip: SkipReason | None = None
) -> None:
    source = SourceKind.INSIGHT.value
    safe_record(increment_checks, source, notification.value)
    if skip is not None:
        safe_record(increment_checks_skipped, source, skip.value)
    if previous_state != new_state:
        safe_record(increment_state_transition, source, previous_state, new_state)


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
    source_detail: dict[str, Any] | None = None,
) -> PlatformAlertOutcome:
    """The one place an outcome is built. Every path goes through the firing decision, because
    an outcome without an episode clears the start of a firing the alert is still in."""
    _record_metrics(notification, check.instance().state, outcome.new_state.value, skip=skip)
    failed = skip in _FAILED_CHECKS
    skipped = skip is not None and not failed
    if check.grouping.mode != GroupingMode.SINGLE and not failed:
        # A grouped check that ran reports through `_decide_grouped`; this one evaluated no group.
        return PlatformAlertOutcome(
            configuration_id=check.id,
            evaluation_key=_evaluation_key(check, now),
            consecutive_failures=outcome.consecutive_failures,
            error_message=error_message,
            disable=disable,
            skipped=skipped,
        )
    return PlatformAlertOutcome.ungrouped(
        configuration_id=check.id,
        evaluation_key=_evaluation_key(check, now),
        consecutive_failures=outcome.consecutive_failures,
        kind=NOTIFICATION_EVENT_KINDS[notification],
        new_state=outcome.new_state.value,
        notified=notified,
        failed=failed,
        firing_episode=decide_firing_episode(snapshot, outcome, now, policy=_policy(check)),
        value=value,
        error_message=error_message,
        query_duration_ms=query_duration_ms,
        disable=disable,
        skipped=skipped,
        source_detail=source_detail,
    )

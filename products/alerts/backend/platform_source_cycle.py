"""Evaluation of due insight alerts on the shared alerts platform.

A parallel run. The production insight fleet evaluates the same alerts against
`AlertConfiguration` and notifies their destinations. This decides what the platform would have
said, and asks for a delivery for the alerts the platform owns and for the alerts in
`LIVE_DELIVERY_INSIGHT_ALERT_IDS`. An owned alert sends without the platform's live delivery flag.
Every other alert on the list still sends only to projects on that flag.

Each platform row resolves to its production alert through `legacy_configuration_id`, because
`check_alert_for_insight` reads the insight, the threshold and the condition off that model. The
query runs the way production runs it, and the verdict comes from the shared machine under
`INSIGHT_ALERT_POLICY`, applied to the platform's own state. `add_alert_check` is the production
writer, and nothing here calls it.

A check that production skips without a query is skipped here too, so both stacks answer the
same set of checks.
"""

import time
import asyncio
from collections.abc import Collection, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Final

from django.conf import settings

import structlog

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.errors import CH_TRANSIENT_ERRORS, QueryErrorCategory, classify_query_error
from posthog.schema_enums import AlertCalculationInterval
from posthog.tasks.alerts.schedule_restriction import is_utc_datetime_blocked
from posthog.tasks.alerts.utils import RenderedInsightChart, render_alert_insight_chart, skip_because_of_weekend
from posthog.temporal.alerts.admission import admit_evaluation_slots, release_evaluation_slot

from products.alerts.backend.evaluation import check_alert_for_insight
from products.alerts.backend.evaluation.contract import AlertExtractionError
from products.alerts.backend.evaluation.dispatcher import PerSeriesEvaluation, check_alert_per_series
from products.alerts.backend.insight_alert_state_machine import INSIGHT_ALERT_POLICY, insight_snapshot
from products.alerts.backend.judge.contract import (
    LLM_DETECTOR_UNAVAILABLE_MESSAGE,
    LLMDetectorMisconfiguredError,
    LLMDetectorUnavailableError,
)
from products.alerts.backend.llm_detector_limits import is_llm_detector_config
from products.alerts.backend.logic.alert_email import INSIGHT_ALERT_ERRORED_EVENT_ID
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_alert_wording import insight_alert_url
from products.alerts_platform.backend.facade.api import due_check_ids, due_checks, refresh_settings, slot_of
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    AlertDeliveryRequest,
    AlertEventKind,
    GroupingMode,
    InstanceCheckState,
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    PlatformAlertUpsert,
    SkipReason,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertConfigurationRecurrenceUnit as RecurrenceUnit
from products.alerts_platform.backend.facade.grouping import (
    GroupObservation,
    bounded_grouping_key,
    decide_groups,
    delivery_parts,
    not_breaching,
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
    increment_checks_deferred,
    increment_checks_skipped,
    increment_state_transition,
    record_scheduler_lag,
    safe_record,
)
from products.alerts_platform.backend.facade.scheduling import (
    REAL_TIME_CADENCE_MINUTES,
    validate_and_normalize_schedule_start_time,
)
from products.cdp.backend.internal_events import LEGACY_INSIGHT_ALERT_EVENT

logger = structlog.get_logger(__name__)

INFLIGHT_KEY = "alerts:platform:insight:evaluations:inflight"

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


# The production insight alerts whose platform evaluations ask for a native delivery while production
# still owns them, as a test. The platform's live delivery flag still has to be on for the project.
# The list stays short because production also sends for these alerts, so each one sends twice.
LIVE_DELIVERY_INSIGHT_ALERT_IDS: Final = frozenset({"01a11d6f-598e-0000-8529-4bcb65526f6d"})

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


# Minutes for the real-time, 15-minute and hourly cadences, a calendar unit for the rest. A calendar
# unit reads its cadence from the unit, so its minutes only feed the shard offset, which an anchored
# unit ignores.
_RECURRENCE: dict[str, tuple[int, str | None]] = {
    AlertCalculationInterval.REAL_TIME: (REAL_TIME_CADENCE_MINUTES, None),
    AlertCalculationInterval.EVERY_15_MINUTES: (15, None),
    AlertCalculationInterval.HOURLY: (60, None),
    AlertCalculationInterval.DAILY: (60 * 24, RecurrenceUnit.DAY),
    AlertCalculationInterval.WEEKLY: (60 * 24 * 7, RecurrenceUnit.WEEK),
    AlertCalculationInterval.MONTHLY: (60 * 24 * 30, RecurrenceUnit.MONTH),
}

# What an edit to an insight alert can change on its copy. The check refreshes these, and the due
# time follows from them, so it is left to the next advance.
SETTINGS_FIELDS: Final = (
    "name",
    "source_config",
    "schedule_restriction",
    "check_interval_minutes",
    "recurrence_unit",
    "anchor_time",
)


def platform_upsert_of(alert: AlertConfiguration) -> PlatformAlertUpsert | None:
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
                "detector": alert.detector_config,
            },
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
        limit=settings.ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_EVALUATIONS,
    )
    if not candidates:
        return ()
    admitted = admit_evaluation_slots(
        list(candidates),
        limit=settings.ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_EVALUATIONS,
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
    """
    # Imported here: at module level it changes how many queries the access-control tests count.
    from posthog.clickhouse.cancel import cancel_query_on_cluster  # noqa: PLC0415

    try:
        cancel_query_on_cluster(team_id, f"{QUERY_ID_PREFIX}{previous_query_id}")
    except Exception:
        logger.exception("Could not stop a timed-out platform insight check", configuration_id=configuration_id)
    release_evaluation_slot(configuration_id, held_until=attempt_slot_token(held_until, attempt - 1), key=INFLIGHT_KEY)
    token = attempt_slot_token(held_until, attempt)
    admitted = admit_evaluation_slots(
        [configuration_id],
        limit=settings.ALERTS_PLATFORM_INSIGHT_MAX_INFLIGHT_EVALUATIONS,
        expires_at=token,
        key=INFLIGHT_KEY,
    )
    return token if admitted else None


def legacy_alerts_of(
    team_id: int, slot: str, cutoff: datetime, configuration_ids: Collection[str]
) -> dict[str, AlertConfiguration]:
    """The production alert behind each due copy that still has one, keyed by the copy's id."""
    if not configuration_ids:
        return {}
    legacy_ids = {
        check.legacy_configuration_id: str(check.id)
        for check in due_checks(
            team_id, SourceKind.INSIGHT.value, slot, cutoff, configuration_ids=list(configuration_ids)
        )
        if check.legacy_configuration_id is not None
    }
    alerts = AlertConfiguration.objects.filter(team_id=team_id, id__in=list(legacy_ids)).only(
        "id", "calculation_interval", "detector_config"
    )
    return {legacy_ids[alert.id]: alert for alert in alerts}


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
    batch, or when its detector no longer matches the worker it was routed to. Writes nothing.

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
        if checks[0].legacy_configuration_id is not None:
            # Production times each check by its own alert's id, so the copy checks at that minute.
            outcome = replace(outcome, schedule_key=str(checks[0].legacy_configuration_id))
        delivery = _delivery(checks[0], outcome)
        return SourceBatchEvaluation(outcomes=(outcome,), deliveries=(delivery,) if delivery is not None else ())
    finally:
        if not retrying:
            release_evaluation_slot(configuration_id, held_until=held_until, key=INFLIGHT_KEY)


def _delivery(check: PlatformAlertCheckInput, outcome: PlatformAlertOutcome) -> AlertDeliveryRequest | None:
    kinds = [group.kind for group in outcome.groups]
    if outcome.failure is not None:
        kinds.append(outcome.failure.kind)
    if not any(kind.value in _EVENT_IDS_BY_KIND for kind in kinds):
        return None
    # Destinations are matched on the legacy alert's id, so a copy without one has nobody to send to.
    if check.legacy_configuration_id is None:
        return None
    legacy_id = str(check.legacy_configuration_id)
    if not check.owned_by_platform and legacy_id not in LIVE_DELIVERY_INSIGHT_ALERT_IDS:
        return None
    return AlertDeliveryRequest(
        source=SourceKind.INSIGHT,
        team_id=check.team_id,
        configuration_id=str(check.id),
        # The recorded key unchanged, so the delivery addresses the row this check wrote.
        evaluation_key=outcome.evaluation_key,
        destination_alert_id=legacy_id,
        event_ids_by_kind=_EVENT_IDS_BY_KIND,
        source_alert_url=_alert_url(check, legacy_id),
        owned_by_platform=check.owned_by_platform,
        overflowed=outcome.overflowed,
        overflow_is_lower_bound=outcome.overflow_is_lower_bound,
        parts=delivery_parts(outcome),
    )


def _alert_url(check: PlatformAlertCheckInput, legacy_id: str) -> str | None:
    """The alert's page on its insight, so a native message links where the insight stack's does."""
    insight_short_id = (
        AlertConfiguration.objects.filter(team_id=check.team_id, id=legacy_id)
        .values_list("insight__short_id", flat=True)
        .first()
    )
    return insight_alert_url(check.team_id, insight_short_id, legacy_id) if insight_short_id else None


def _legacy_alert(check: PlatformAlertCheckInput) -> AlertConfiguration | None:
    if check.legacy_configuration_id is None:
        return None
    return (
        AlertConfiguration.objects.select_related("insight", "team", "threshold", "created_by")
        .filter(team_id=check.team_id, id=check.legacy_configuration_id)
        .first()
    )


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
    alert = _legacy_alert(check)
    if alert is None:
        # The production alert is gone, so this copy can never be compared again.
        return _skipped(check, snapshot, now=now, disable=True)
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
    if check.grouping.mode != GroupingMode.SINGLE:
        return _decide_grouped(check, snapshot, alert, now=now)
    started_at = time.monotonic()
    try:
        result = check_alert_for_insight(alert, evaluation_id=evaluation_id)
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
        )
    except (AlertExtractionError, LLMDetectorMisconfiguredError) as error:
        return _broken(check, snapshot, alert, now=now, message=str(error))
    except Exception as error:
        return _query_failed(check, snapshot, alert, error, now=now)
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
        firing=(alert, result.breaches or []),
    )


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

# A breakdown value can be muted on its own, which production cannot express, so the platform's
# mute applies: the value is still judged and only its announcement is held. A snooze of the
# production alert never reaches here, because `_decide` records that check without a query.
GROUPED_INSIGHT_ALERT_POLICY: Final = replace(INSIGHT_ALERT_POLICY, mute_gates_notification_only=True)


def _decide_grouped(
    check: PlatformAlertCheckInput, snapshot: AlertSnapshot, alert: AlertConfiguration, *, now: datetime
) -> PlatformAlertOutcome:
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
        evaluated = check_alert_per_series(alert)
    except AlertExtractionError as error:
        return _broken(check, snapshot, alert, now=now, message=str(error))
    except Exception as error:
        return _query_failed(check, snapshot, alert, error, now=now)
    if not isinstance(evaluated, PerSeriesEvaluation):
        return _skipped(check, snapshot, now=now)
    duration_ms = int((time.monotonic() - started_at) * 1000)

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
        for series in evaluated.series:
            key, found = bounded_grouping_key(series.identity), series.result.breaches or []
            if key not in breaches or (found and not breaches[key]):
                breaches[key] = found
        # One render serves every value that fires, because they all show the same insight.
        chart = _chart(check, alert)
        decision = replace(
            decision,
            verdicts=tuple(
                replace(
                    verdict,
                    group=replace(
                        verdict.group,
                        source_detail=_detail(alert, breaches.get(verdict.group.grouping_key, []), chart),
                    ),
                )
                if verdict.outcome.notification == NotificationAction.FIRE
                else verdict
                for verdict in decision.verdicts
            ),
        )
    return decision.as_outcome(
        configuration_id=check.id,
        evaluation_key=_evaluation_key(check, now),
        grouping=check.grouping,
        query_duration_ms=duration_ms,
        results_cut=evaluated.truncated,
    )


def _firing_detail(
    check: PlatformAlertCheckInput, alert: AlertConfiguration, breaches: Sequence[str]
) -> dict[str, Any]:
    """What production's `$insight_alert_firing` carries beside the verdict, which only the check can know."""
    return _detail(alert, breaches, _chart(check, alert))


def _chart(check: PlatformAlertCheckInput, alert: AlertConfiguration) -> RenderedInsightChart | None:
    # A render takes up to a minute and a half, so only an alert the platform delivers for pays
    # for one. Production renders no chart for a real-time alert either.
    if check.owned_by_platform and alert.calculation_interval != AlertCalculationInterval.REAL_TIME:
        return render_alert_insight_chart(alert)
    return None


def _context(alert: AlertConfiguration) -> dict[str, Any]:
    """The insight a message names and links to, which every message about the alert carries."""
    return {"insight_name": alert.insight.name, "insight_short_id": alert.insight.short_id}


def _clipped(breach: str) -> str:
    return breach if len(breach) <= MAX_BREACH_CHARS else breach[: MAX_BREACH_CHARS - 1] + "…"


def _detail(alert: AlertConfiguration, breaches: Sequence[str], chart: RenderedInsightChart | None) -> dict[str, Any]:
    # Bounded, because the outcome crosses into Temporal and a breach names user-written labels.
    detail: dict[str, Any] = {
        "breaches": [_clipped(breach) for breach in breaches[:MAX_DETAIL_BREACHES]],
        **_context(alert),
        # The legacy alert's id, which a native message's snooze menu snoozes.
        "alert_id": str(alert.id),
    }
    if chart is not None:
        # The ids rather than a URL, because the URL opens the chart without a login and history keeps
        # this for its whole retention. A delivery mints the URL when it sends.
        detail["insight_chart_asset_id"] = chart.asset_id
        detail["insight_chart_render_user_id"] = chart.render_user_id
    return detail


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
    context: dict[str, Any] | None = None,
) -> PlatformAlertOutcome:
    outcome = evaluate_alert_check(snapshot, check_input, now, policy=INSIGHT_ALERT_POLICY)
    source_detail: dict[str, Any] | None
    if firing is not None and outcome.notification == NotificationAction.FIRE:
        source_detail = _firing_detail(check, *firing)
    elif outcome.notification != NotificationAction.NONE:
        source_detail = context
    else:
        source_detail = None
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
        firing_episode=decide_firing_episode(snapshot, outcome, now, policy=INSIGHT_ALERT_POLICY),
        value=value,
        error_message=error_message,
        query_duration_ms=query_duration_ms,
        disable=disable,
        skipped=skipped,
        source_detail=source_detail,
    )

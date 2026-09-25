import json
import time
import asyncio
import hashlib
import threading
import traceback
import contextlib
import contextvars
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from typing import ParamSpec, TypeVar

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Min, Q, Value, When, Window
from django.db.models.functions import Coalesce, RowNumber

import structlog
import temporalio.activity
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.schema import AlertState

from posthog.hogql.errors import TableAccessDeniedError

from posthog.clickhouse.cancel import cancel_query_on_cluster
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.email import is_email_available
from posthog.errors import (
    CH_TRANSIENT_ERRORS,
    CHQueryErrorQueryWasCancelled,
    CHQueryErrorS3Error,
    CHQueryErrorS3FileChangedDuringRead,
)
from posthog.exceptions import QueryRanConcurrently
from posthog.exceptions_capture import capture_exception
from posthog.query_creator_access import creator_access_revoked, report_creator_access_revoked
from posthog.schema_migrations.upgrade_manager import upgrade_insight
from posthog.sync import database_sync_to_async
from posthog.tasks.alerts.investigation_notifications import run_investigation_notification_safety_net
from posthog.tasks.alerts.metrics_investigation import run_metrics_alert_investigation, should_investigate_metrics_alert
from posthog.tasks.alerts.schedule_restriction import is_utc_datetime_blocked, next_unblocked_utc
from posthog.tasks.alerts.utils import (
    CALCULATION_INTERVAL_ORDER,
    add_alert_check,
    disable_invalid_alert,
    dispatch_alert_notification,
    get_alert_error_notification_recipients,
    next_check_time,
    next_scheduled_check_time,
    record_alert_delivery,
    skip_because_of_weekend,
)
from posthog.temporal.alerts.admission import (
    admit_evaluation_slots,
    hold_evaluation_slot,
    inflight_alert_ids,
    max_inflight_evaluations,
    refresh_evaluation_slot,
    release_evaluation_slot,
    release_evaluation_slots,
)
from posthog.temporal.alerts.investigation import claim_investigation_slot, decide_investigation
from posthog.temporal.alerts.metrics import record_ai_detector_check_outcome, record_due_insight_alert_metrics
from posthog.temporal.alerts.retry_policy import ALERT_PREPARE_RETRY_POLICY, SlotLease, alert_timeouts
from posthog.temporal.alerts.types import (
    AdmitEvaluationsInputs,
    AdmittedEvaluations,
    AlertInfo,
    EvaluateAlertActivityInputs,
    EvaluateAlertResult,
    NotifyAlertActivityInputs,
    PrepareAction,
    PrepareAlertActivityInputs,
    PrepareAlertResult,
    RecordFailedEvaluationActivityInputs,
    RecordFailedEvaluationResult,
    ReleaseEvaluationSlotsInputs,
    ScheduleDueAlertChecksWorkflowInputs,
    SkipReason,
)
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.metrics import get_metric_meter

from products.alerts.backend.evaluation import check_alert_for_insight
from products.alerts.backend.evaluation.contract import (
    EVALUATION_TEMPORARILY_UNAVAILABLE_ERROR_CODE,
    EVALUATION_TEMPORARILY_UNAVAILABLE_MESSAGE,
    AlertDataUnavailableError,
    AlertExtractionError,
)
from products.alerts.backend.evaluation.validation import validate_alert_config, validate_alert_insight_query
from products.alerts.backend.facade.api import (
    LLM_DETECTOR_UNAVAILABLE_ERROR_CODE,
    LLM_DETECTOR_UNAVAILABLE_MESSAGE,
    MAX_CONCURRENT_MODEL_CALLS,
    LLMDetectorMisconfiguredError,
    LLMDetectorUnavailableError,
    is_llm_detector_config,
)
from products.alerts.backend.facade.destinations import count_active_alert_destinations
from products.alerts.backend.insight_alert_state_machine import apply_unsnooze
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, Threshold
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    SourceType,
    TargetType,
    create_notification,
)
from products.product_analytics.backend.facade.api import lock_insight_for_evaluation

logger = structlog.get_logger(__name__)

_T = TypeVar("_T")
_P = ParamSpec("_P")

# Slow evaluations must not occupy the threads that renew their leases or cancel their queries.
_ADMISSION_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="insight-alert-admission")
_CANCELLATION_EXECUTOR = ThreadPoolExecutor(max_workers=10, thread_name_prefix="insight-alert-cancel")


async def _run_control(
    executor: ThreadPoolExecutor, function: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs
) -> _T:
    context = contextvars.copy_context()
    return await asyncio.get_running_loop().run_in_executor(executor, partial(context.run, function, *args, **kwargs))


_NOTIFICATION_DELIVERY_EXECUTOR = ThreadPoolExecutor(max_workers=10, thread_name_prefix="insight-alert-delivery")

# AI-detector checks hold a thread for the model call, up to a minute each. On the shared
# default pool that would let a slow model stall every alert's database work on the worker,
# so they run on their own pool, sized to the detector's own concurrency bound. A check
# past that bound queues here without holding any thread.
_LLM_EVALUATE_EXECUTOR = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_MODEL_CALLS, thread_name_prefix="insight-alert-llm-evaluate"
)


@frozen
class _RetrievedAlerts:
    alerts: list[AlertInfo]
    due_count: int
    oldest_due_at: datetime | None
    polled_at: datetime
    in_flight_count: int


@temporalio.activity.defn
async def retrieve_due_alerts(inputs: ScheduleDueAlertChecksWorkflowInputs | None = None) -> list[AlertInfo]:
    if inputs is None:
        inputs = ScheduleDueAlertChecksWorkflowInputs()

    @database_sync_to_async(thread_sensitive=False)
    def get_alerts() -> _RetrievedAlerts:
        polled_at = datetime.now(UTC)

        calculation_interval_order = Case(
            *(
                When(calculation_interval=interval.value, then=Value(order))
                for interval, order in CALCULATION_INTERVAL_ORDER.items()
            ),
            default=Value(max(CALCULATION_INTERVAL_ORDER.values())),
            output_field=IntegerField(),
        )

        due_alerts_query = (
            AlertConfiguration.objects.filter(
                Q(enabled=True, next_check_at__lte=polled_at) | Q(enabled=True, next_check_at__isnull=True)
            )
            .filter(Q(snoozed_until__isnull=True) | Q(snoozed_until__lt=polled_at))
            .filter(insight__deleted=False)
        )
        # A check stays due until it finishes, so admitted alerts would otherwise be handed out again.
        in_flight = inflight_alert_ids()
        selectable_query = due_alerts_query.exclude(id__in=in_flight) if in_flight else due_alerts_query
        alerts_query = (
            selectable_query.annotate(_interval_order=calculation_interval_order)
            .annotate(
                _team_rank=Window(
                    expression=RowNumber(),
                    partition_by=[F("team_id")],
                    order_by=[
                        F("_interval_order").asc(),
                        F("next_check_at").asc(nulls_first=True),
                        F("id").asc(),
                    ],
                ),
            )
            .order_by(
                "_team_rank",
                "_interval_order",
                F("next_check_at").asc(nulls_first=True),
                "team_id",
                "id",
            )
            .only("id", "team_id", "calculation_interval", "insight_id")[: inputs.max_alerts_per_run]
        )

        alerts = [
            AlertInfo(
                alert_id=str(a.id),
                team_id=a.team_id,
                distinct_id=str(a.id),
                calculation_interval=a.calculation_interval,
                insight_id=a.insight_id,
            )
            for a in alerts_query
        ]

        due_alert_metrics = due_alerts_query.aggregate(
            due_count=Count("id"), oldest_due_at=Min(Coalesce("next_check_at", "created_at"))
        )
        return _RetrievedAlerts(
            alerts=alerts,
            due_count=due_alert_metrics["due_count"],
            oldest_due_at=due_alert_metrics["oldest_due_at"],
            polled_at=polled_at,
            in_flight_count=len(in_flight),
        )

    retrieved = await get_alerts()
    try:
        await asyncio.to_thread(
            record_due_insight_alert_metrics,
            retrieved.due_count,
            retrieved.oldest_due_at,
            retrieved.polled_at,
        )
    except Exception:
        logger.exception("Failed to record due insight alert metrics")

    try:
        meter = get_metric_meter()
        meter.create_counter(
            "insight_alert_scheduler_capacity",
            "Alert scheduling capacity made available across successful retrieval runs",
        ).add(inputs.max_alerts_per_run)
        meter.create_counter(
            "insight_alert_scheduler_alerts_selected",
            "Due alerts selected across successful alert scheduler retrieval runs",
        ).add(len(retrieved.alerts))
        meter.create_gauge("insight_alert_evaluations_inflight", "Alert checks holding an evaluation slot").set(
            retrieved.in_flight_count
        )
    except Exception:
        logger.exception("Failed to record alert scheduler capacity metrics")
    return retrieved.alerts


@temporalio.activity.defn
async def admit_alert_evaluations(inputs: AdmitEvaluationsInputs) -> AdmittedEvaluations:
    admitted = await _run_control(
        _ADMISSION_EXECUTOR,
        admit_evaluation_slots,
        inputs.alert_ids,
        limit=max_inflight_evaluations(),
        expires_at=inputs.expires_at,
    )
    try:
        get_metric_meter().create_counter(
            "insight_alert_evaluations_admitted", "Alert checks admitted to an evaluation slot"
        ).add(len(admitted))
    except Exception:
        logger.exception("Failed to record alert admission metrics")
    return AdmittedEvaluations(alert_ids=admitted)


@temporalio.activity.defn
async def release_alert_evaluation_slots(inputs: ReleaseEvaluationSlotsInputs) -> None:
    await _run_control(_ADMISSION_EXECUTOR, release_evaluation_slots, inputs.alert_ids, held_until=inputs.held_until)


def _has_active_destinations(alert: AlertConfiguration) -> bool:
    return (
        count_active_alert_destinations(
            team_id=alert.team_id,
            alert_id=str(alert.id),
            allowed_event_ids={"$insight_alert_firing"},
        )
        > 0
    )


# How often a waiting attempt looks again: for a free slot before it runs its query, or for its
# thread to exit after the query was killed.
_SLOT_POLL_SECONDS = 5.0

_SLOT_LOST_ERROR_TYPE = "EvaluationSlotLost"


class _EvaluationStopped(Exception):
    """Raised in the evaluation thread once its attempt's cancellation began, so it records nothing."""


async def _hold_evaluation_slot_before_running(alert_id: str, *, lease_seconds: float) -> float:
    """Hold the slot for evaluate_alert, waiting while there is no room or Redis is unreachable.

    An id that lapsed from the set is no longer admitted, and running its query anyway would put it
    over the limit, so it waits for room until its budget cancels it. Redis being unreachable waits
    too instead of failing the check, because an outage shorter than the budget then costs nothing.
    """
    waited_since: float | None = None
    while True:
        try:
            held_until = await _run_control(
                _ADMISSION_EXECUTOR,
                hold_evaluation_slot,
                alert_id,
                limit=max_inflight_evaluations(),
                lease_seconds=lease_seconds,
            )
        except Exception:
            if waited_since is None:
                logger.exception("alerts.admission.hold_failed", alert_id=alert_id)
            held_until = None
        if held_until is not None:
            if waited_since is not None:
                logger.info("alerts.admission.slot_waited", alert_id=alert_id, seconds=time.time() - waited_since)
            return held_until
        if waited_since is None:
            waited_since = time.time()
        await asyncio.sleep(_SLOT_POLL_SECONDS)


def _attempt_will_retry(error: Exception, retry_policy: RetryPolicy) -> bool:
    if isinstance(error, ApplicationError):
        if error.non_retryable:
            return False
        error_type = error.type
    else:
        error_type = type(error).__name__
    if error_type in (retry_policy.non_retryable_error_types or ()):
        return False
    return not retry_policy.maximum_attempts or temporalio.activity.info().attempt < retry_policy.maximum_attempts


class _SlotHolder:
    """The evaluation slot one attempt holds, identified by the expiry it last wrote."""

    def __init__(self, alert_id: str, held_until: float | None) -> None:
        self.alert_id = alert_id
        self.held_until = held_until
        self.lost = False
        self._stop = asyncio.Event()
        self._refresher: asyncio.Task[None] | None = None

    @contextlib.asynccontextmanager
    async def refreshing(self, lease: SlotLease | None, *, on_lost: Callable[[], object]) -> AsyncIterator[None]:
        """Re-hold the slot under the lease while the body runs, and call on_lost once it cannot be kept.

        The lease makes a slot lapse soon after its worker dies. The same lapse would let the
        scheduler reuse the slot of a live attempt that cannot reach Redis, so that attempt is
        stopped first, while it is still counted.
        """
        if lease is None or self.held_until is None:
            yield
            return
        self._refresher = asyncio.create_task(self._refresh_until(lease, on_lost))
        try:
            yield
        finally:
            await self._stop_refreshing()

    async def _stop_refreshing(self) -> None:
        # Wait for the refresher rather than cancel it, so a refresh in flight cannot write a new
        # expiry after a release has checked the old one.
        if self._refresher is None:
            return
        self._stop.set()
        await self._refresher
        self._refresher = None

    async def _refresh_until(self, lease: SlotLease, on_lost: Callable[[], object]) -> None:
        refresh_seconds = lease.refresh.total_seconds()
        while (held_until := self.held_until) is not None:
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=refresh_seconds)
                return
            except TimeoutError:
                pass
            expires_at = time.time() + lease.lease.total_seconds()
            try:
                owned = await _run_control(
                    _ADMISSION_EXECUTOR,
                    refresh_evaluation_slot,
                    self.alert_id,
                    held_until=held_until,
                    expires_at=expires_at,
                )
            except Exception:
                logger.exception("alerts.admission.refresh_failed", alert_id=self.alert_id)
                # Stop with a refresh interval to spare, so the query is dead before the slot lapses
                # and the kill that stops it has time to land.
                if time.time() + refresh_seconds < held_until - refresh_seconds:
                    continue
                self.lost = True
                on_lost()
                return
            if not owned:
                # Another attempt took the slot over, or it lapsed while Redis was unreachable.
                # Either way this attempt is no longer admitted and has nothing left to release.
                self.held_until = None
                self.lost = True
                on_lost()
                return
            self.held_until = expires_at

    async def release(self) -> None:
        await self._stop_refreshing()
        if self.held_until is not None:
            await _run_control(_ADMISSION_EXECUTOR, release_evaluation_slot, self.alert_id, held_until=self.held_until)


async def _finish(cleanup: Awaitable[_T]) -> _T:
    """Await cleanup even if this task is cancelled again while it runs.

    Once the server has timed an attempt out it may cancel the task once more for each heartbeat it
    no longer recognises, and a cleanup cut short would leave a running query nobody stops.
    """
    task = asyncio.ensure_future(cleanup)
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            pass
    return task.result()


async def _run_holding_slot(
    alert_id: str,
    held_until: float | None,
    run: Callable[[], Awaitable[_T]],
    *,
    retry_policy: RetryPolicy,
    keeps_slot: Callable[[_T], bool],
    lease: SlotLease | None = None,
    stop_work: Callable[[], Awaitable[bool]] | None = None,
) -> _T:
    """Run one attempt of a check while it holds its evaluation slot.

    With a lease the slot is re-held for as long as the attempt runs, so a worker that dies frees it
    soon after. Without one it stays until the scheduler's expiry, which suits prepare_alert: its
    attempts run without a heartbeat timeout, so a slow one cannot be presumed dead.

    The slot is released when the attempt finishes for good: a result keeps_slot rejects, a failure
    Temporal will not retry, or a cancellation. A retryable failure keeps it, because releasing
    during the backoff lets the scheduler admit past the limit under the very overload that causes
    the retries; the next attempt's hold takes the slot over.

    An attempt stops early when Temporal cancels it or when the slot can no longer be held, and
    runs stop_work to completion before it gives the slot back. When Redis is unreachable it stops
    a refresh interval before the slot lapses, so its work ends while it is still counted. When a
    retried attempt takes the slot over, the old attempt learns it only on its next refresh, so the
    two overlap under one slot for up to one refresh interval. Work that stop_work could not stop
    keeps the slot, which lapses on its own once nothing refreshes it. A lost slot fails the
    attempt with a retryable error, and a retry waits for a slot of its own.
    """
    holder = _SlotHolder(alert_id, held_until)
    body = asyncio.ensure_future(run())
    async with holder.refreshing(lease, on_lost=body.cancel), Heartbeater():
        try:
            result = await body
        except asyncio.CancelledError:
            body.cancel()
            stopped = True
            if stop_work is not None:
                stopped = await _finish(stop_work())
            if stopped:
                await _finish(holder.release())
            if holder.lost and not temporalio.activity.is_cancelled():
                raise ApplicationError("The evaluation lost its admission slot", type=_SLOT_LOST_ERROR_TYPE)
            raise
        except Exception as error:
            if not _attempt_will_retry(error, retry_policy):
                await holder.release()
            raise
    if not keeps_slot(result):
        await holder.release()
    return result


@temporalio.activity.defn
async def prepare_alert(inputs: PrepareAlertActivityInputs) -> PrepareAlertResult:
    """Load the alert, validate its config, and decide whether to evaluate."""

    @database_sync_to_async(thread_sensitive=False)
    def _prepare() -> PrepareAlertResult:
        try:
            alert = AlertConfiguration.objects.select_related("insight", "team", "team__organization", "threshold").get(
                id=inputs.alert_id
            )
        except AlertConfiguration.DoesNotExist:
            logger.warning("Alert not found", alert_id=inputs.alert_id)
            return PrepareAlertResult(action=PrepareAction.SKIP, reason=SkipReason.NOT_FOUND)

        if not alert.enabled:
            logger.info("Skipping disabled alert", alert_id=inputs.alert_id)
            return PrepareAlertResult(action=PrepareAction.SKIP, reason=SkipReason.DISABLED)

        if alert.insight.deleted:
            logger.info(
                "Skipping alert for deleted insight",
                alert_id=inputs.alert_id,
                insight_id=alert.insight_id,
            )
            return PrepareAlertResult(action=PrepareAction.SKIP, reason=SkipReason.INSIGHT_DELETED)

        wants_email = bool(alert.get_subscribed_users_emails())
        if wants_email and not is_email_available() and not _has_active_destinations(alert):
            reason = "Email delivery is unavailable on this instance. Configure email before re-enabling this alert."
            disable_invalid_alert(alert, reason, notify_subscribers=False, error_code="email_unavailable")
            return PrepareAlertResult(action=PrepareAction.AUTO_DISABLE, reason=reason)

        # Plan downgrade protection: entitlement-gated intervals must stop evaluating when the
        # org loses the feature (e.g. billing downgrade), since API validation only runs on writes.
        entitlement_error = AlertConfiguration.interval_entitlement_error(
            calculation_interval=alert.calculation_interval,
            organization=alert.team.organization,
        )
        if entitlement_error:
            disable_invalid_alert(alert, entitlement_error)
            return PrepareAlertResult(action=PrepareAction.AUTO_DISABLE, reason=entitlement_error)

        now = datetime.now(UTC)

        if alert.next_check_at and alert.next_check_at > now:
            logger.info(
                "Alert took too long to compute or was queued too long during which it already got "
                "computed. So not attempting to compute it again until it's due next",
                alert=alert,
            )
            return PrepareAlertResult(action=PrepareAction.SKIP, reason=SkipReason.NOT_DUE)

        if skip_because_of_weekend(alert):
            logger.info("Skipping alert check because weekend checking is disabled", alert=alert)
            alert.next_check_at = next_check_time(alert)
            alert.save(update_fields=["next_check_at"])
            return PrepareAlertResult(action=PrepareAction.SKIP, reason=SkipReason.WEEKEND)

        if is_utc_datetime_blocked(alert, now):
            logger.info(
                "Skipping alert check because of schedule restriction (quiet hours)",
                alert_id=alert.id,
            )
            alert.next_check_at = next_unblocked_utc(alert, now)
            alert.save(update_fields=["next_check_at"])
            return PrepareAlertResult(action=PrepareAction.SKIP, reason=SkipReason.QUIET_HOURS)

        if alert.snoozed_until:
            if alert.snoozed_until > now:
                logger.info("Alert has been snoozed so skipping checking it now", alert=alert)
                return PrepareAlertResult(action=PrepareAction.SKIP, reason=SkipReason.SNOOZED)
            # Snooze expired — persist clear so evaluate_alert reads the fresh state.
            alert.snoozed_until = None
            state_fields = apply_unsnooze(alert)
            alert.save(update_fields=["snoozed_until", *state_fields])

        # Query upgrades mutate the in-memory insight. Track the saved inputs before
        # validation so a schema upgrade is not mistaken for a concurrent edit.
        evaluation_fingerprint = _evaluation_fingerprint(alert)
        try:
            insight = alert.insight
            with upgrade_insight(insight):
                if insight.query is None:
                    raise ValueError("Alert's insight has no valid query")
                threshold_config = alert.threshold.configuration if alert.threshold else None
                validate_alert_insight_query(insight.query, team=alert.team, user=alert.created_by)
                validate_alert_config(
                    insight.query,
                    alert.condition,
                    alert.config,
                    threshold_config,
                    alert.calculation_interval,
                    detector_config=alert.detector_config,
                )
        except ValueError as e:
            disable_invalid_alert(alert, str(e))
            return PrepareAlertResult(action=PrepareAction.AUTO_DISABLE, reason=str(e))

        return PrepareAlertResult(
            action=PrepareAction.EVALUATE,
            uses_llm_detector=is_llm_detector_config(alert.detector_config),
            evaluation_fingerprint=evaluation_fingerprint,
        )

    # The scheduler's reservation names no owner, and prepare_alert runs without a heartbeat timeout,
    # so a timed-out attempt that finishes late would otherwise remove the lease a retried attempt holds.
    # No room means the reservation lapsed and the set filled up; prepare runs no query, so it goes
    # on without a slot and evaluate_alert waits for one.
    try:
        held_until = await _run_control(
            _ADMISSION_EXECUTOR, hold_evaluation_slot, inputs.alert_id, limit=max_inflight_evaluations()
        )
    except Exception:
        logger.exception("alerts.admission.hold_failed", alert_id=inputs.alert_id)
        held_until = None
    return await _run_holding_slot(
        inputs.alert_id,
        held_until,
        _prepare,
        retry_policy=ALERT_PREPARE_RETRY_POLICY,
        keeps_slot=lambda result: result.action == PrepareAction.EVALUATE,
    )


# Temporal gives the activity only the class name of the failure, so match on names.
# The S3 errors come from the files behind one warehouse table. A file that is broken or that the
# cluster cannot read fails every check, so these errors still retry but then reach the owner.
_SHARED_CH_FAILURE_NAMES = frozenset(
    error_class.__name__
    for error_class in CH_TRANSIENT_ERRORS
    if error_class not in (CHQueryErrorS3Error, CHQueryErrorS3FileChangedDuringRead)
)


def _is_transient_failure(inputs: RecordFailedEvaluationActivityInputs) -> bool:
    """True when the retries ran out on a ClickHouse failure that is not specific to this alert.

    A cluster outage stops every alert that checks in the same window. If each of them goes to
    ERRORED and emails its owner, one outage sends one generic email per alert.
    """
    return inputs.error_type in _SHARED_CH_FAILURE_NAMES


def _failed_evaluation_error(inputs: RecordFailedEvaluationActivityInputs) -> dict:
    """The error payload for an evaluation that ran out of retries without writing a check.

    A provider the judge cannot reach, or a shared ClickHouse failure, is not the owner's
    configuration, and the raw transport error is not written for them, so those cases get
    their own code and their own wording.
    """
    if inputs.error_type == LLMDetectorUnavailableError.__name__:
        return {"code": LLM_DETECTOR_UNAVAILABLE_ERROR_CODE, "message": LLM_DETECTOR_UNAVAILABLE_MESSAGE}
    if _is_transient_failure(inputs):
        return {
            "code": EVALUATION_TEMPORARILY_UNAVAILABLE_ERROR_CODE,
            "message": EVALUATION_TEMPORARILY_UNAVAILABLE_MESSAGE,
        }
    return {"message": inputs.error_message}


def _write_errored_alert_check(
    alert: AlertConfiguration, error: dict, *, is_transient_error: bool = False
) -> tuple[AlertCheck, bool]:
    """Write an errored AlertCheck for an already-locked alert and return it with the notify decision.

    Both evaluate_alert's failure path and the retry-exhausted record_failed_evaluation activity go
    through here, so the errored-check write stays in one place.
    """
    return add_alert_check(alert, None, error, is_transient_error=is_transient_error)


@temporalio.activity.defn
async def evaluate_alert(inputs: EvaluateAlertActivityInputs) -> EvaluateAlertResult:
    """Run the insight ClickHouse query, apply the state machine, persist an AlertCheck row."""
    info = temporalio.activity.info()
    evaluation_id = f"{info.workflow_run_id}:{info.activity_id}"
    # Keep detector idempotency stable, but prevent cleanup from cancelling a replacement attempt.
    query_id = f"{evaluation_id}:{info.attempt}:"
    # Set once cancellation begins. A kill misses a query that has not started or that finishes
    # between two kills, and a thread abandoned after the kill budget can wake up later, so the
    # thread itself checks this before it queries and before it records. An attempt that a retry
    # replaced learns it only on its next slot refresh, so a query that finishes before then still
    # records.
    stopping = threading.Event()

    def _stop_if_cancelled() -> None:
        if stopping.is_set():
            raise _EvaluationStopped()

    def _evaluate(alert: AlertConfiguration) -> EvaluateAlertResult:
        _stop_if_cancelled()
        evaluated_alert = alert
        evaluated_fingerprint = _evaluation_fingerprint(alert)
        # CH workload management keys off these tags to isolate alert queries from other tenants.
        # calculation_interval / config_type also let query_log cost be grouped by alert cadence
        # (real_time vs every_15_minutes vs ...) and query shape (trends vs HogQL) without a join.
        # client_query_id names every query of this attempt, so a cancelled attempt can kill them.
        tag_queries(
            team_id=alert.team_id,
            client_query_id=query_id,
            alert_config_id=str(alert.id),
            product=Product.PRODUCT_ANALYTICS,
            feature=Feature.ALERTING,
            alert_calculation_interval=alert.calculation_interval,
            alert_config_type=(alert.config or {}).get("type"),
        )

        breaches: list[str] | None = None
        error: dict | None = None
        invalid_configuration: str | None = None
        alert_evaluation_result = None

        try:
            alert_evaluation_result = check_alert_for_insight(alert, evaluation_id=evaluation_id)
            breaches = alert_evaluation_result.breaches
            if is_llm_detector_config(alert.detector_config):
                record_ai_detector_check_outcome("evaluated")
        except CH_TRANSIENT_ERRORS:
            raise
        except QueryRanConcurrently:
            # A query single-flight follower gets this error when its leader fails in a way that the
            # flight cannot share, such as a cluster at capacity. Re-raise it so that the retry runs
            # the query again and handles the leader's real error.
            raise
        except CHQueryErrorQueryWasCancelled:
            # A cancelled attempt kills its query and decides what to record; the thread it left
            # behind must not write a check of its own.
            raise
        except AlertDataUnavailableError as err:
            error = {"message": str(err)}
        except LLMDetectorUnavailableError:
            # An LLM detector that couldn't reach a verdict must not resolve to "not firing":
            # re-raise so the retry policy gets another attempt. Once the attempts run out the
            # retry-exhausted path records an errored check, the same outcome as any other
            # evaluation that never produced a value.
            raise
        except LLMDetectorMisconfiguredError as err:
            # Same fail-loud outcome as a bad query shape below, counted apart because a
            # withdrawn consent or rollout is the owner's to fix and never a provider failure.
            record_ai_detector_check_outcome("misconfigured")
            invalid_configuration = str(err)
        except AlertExtractionError as err:
            # The alert can't be evaluated as configured (wrong query shape / bad config) — a
            # deliberate fail-loud outcome, not a bug. Auto-disable and email the owner via the
            # existing path instead of capturing it as an exception, which would pollute error
            # tracking with a config problem that recurs on every check until fixed.
            invalid_configuration = str(err)
        except TableAccessDeniedError as err:
            logger.exception("Alert failed to evaluate", alert_id=alert.id, exc_info=err)
            # A revoked creator's access-denied error is a known limitation - report it as an event
            # rather than capturing it, which would recur on every check until the alert is fixed.
            if creator_access_revoked(alert.created_by, alert.team):
                report_creator_access_revoked(
                    user=alert.created_by,
                    team=alert.team,
                    source="alert",
                    error=err,
                    properties={"alert_id": str(alert.id), "insight_id": alert.insight_id},
                )
                error = {"message": str(err)}
            else:
                capture_exception(
                    err,
                    additional_properties={
                        "alert_configuration_id": str(alert.id),
                        "insight_id": alert.insight_id,
                        "team_id": alert.team_id,
                    },
                )
                error = {"message": str(err), "traceback": traceback.format_exc()}
        except Exception as err:
            logger.exception("Alert failed to evaluate", alert_id=alert.id, exc_info=err)
            capture_exception(
                err,
                additional_properties={
                    "alert_configuration_id": str(alert.id),
                    "insight_id": alert.insight_id,
                    "team_id": alert.team_id,
                },
            )
            error = {"message": str(err), "traceback": traceback.format_exc()}

        should_start_investigation = False
        should_gate_notification = False
        should_run_metrics_investigation = False
        _stop_if_cancelled()
        with transaction.atomic():
            current_alert = _lock_evaluation_alert(
                alert_id=inputs.alert_id, team_id=evaluated_alert.team_id, insight_id=evaluated_alert.insight_id
            )
            _stop_if_cancelled()
            if current_alert is None or not _evaluation_inputs_match(evaluated_fingerprint, current_alert):
                # Leave the current state and due time intact. The next scheduler tick can
                # evaluate the edited alert; a disabled or deleted alert needs no further work.
                return EvaluateAlertResult(
                    alert_check_id=None,
                    should_notify=False,
                    new_state=AlertState(current_alert.state if current_alert else evaluated_alert.state),
                )
            alert = current_alert
            if invalid_configuration is not None:
                alert_check = disable_invalid_alert(
                    alert, invalid_configuration, notify_subscribers=False, error_code="invalid_configuration"
                )
                return EvaluateAlertResult(
                    alert_check_id=str(alert_check.id), should_notify=True, new_state=AlertState.ERRORED
                )
            if error is not None:
                alert_check, should_notify = _write_errored_alert_check(alert, error)
                return EvaluateAlertResult(
                    alert_check_id=str(alert_check.id), should_notify=should_notify, new_state=AlertState.ERRORED
                )
            previous_state = alert.state
            alert_check, should_notify = add_alert_check(alert, alert_evaluation_result, error)

            investigation = decide_investigation(alert, alert_check)
            if investigation.should_investigate and claim_investigation_slot(alert, alert_check):
                should_start_investigation = True
                should_gate_notification = investigation.is_first_of_episode and bool(
                    alert.investigation_gates_notifications
                )

            # Claim the cooldown slot inside the transaction so a flapping or
            # concurrently-retried alert can't pile up investigations.
            if should_investigate_metrics_alert(
                alert, previous_state=previous_state, new_state=alert_check.state
            ) and claim_investigation_slot(alert, alert_check):
                should_run_metrics_investigation = True

        # Outside the persistence transaction: the metrics investigation issues
        # ClickHouse queries and must never hold the row lock; a failure is
        # recorded on the check and can't affect the alert outcome.
        if should_run_metrics_investigation:
            run_metrics_alert_investigation(alert, alert_check)

        return EvaluateAlertResult(
            alert_check_id=str(alert_check.id),
            should_notify=should_notify,
            new_state=AlertState(alert_check.state),
            breaches=breaches,
            should_start_investigation=should_start_investigation,
            should_gate_notification=should_gate_notification,
            investigation_user_id=alert.created_by_id if should_start_investigation else None,
        )

    team_id = inputs.team_id
    thread: asyncio.Future[EvaluateAlertResult] | None = None

    async def _load_and_evaluate() -> EvaluateAlertResult:
        nonlocal team_id, thread
        # Route and evaluate the same snapshot. A second read after choosing the executor
        # could pick up an AI detector and run its model call on the shared pool.
        alert = await _load_alert_for_evaluation(inputs)
        team_id = alert.team_id
        uses_llm_detector = is_llm_detector_config(alert.detector_config)
        if uses_llm_detector != inputs.uses_llm_detector:
            # The prepare phase picked the task queue from the detector type it read, and only
            # the AI worker holds the model credentials. An edit since then means this worker may
            # not be able to run the alert as it now stands, so leave it to the next scheduler
            # tick, which prepares and routes it again.
            logger.info("alerts.skip_detector_type_changed", alert_id=inputs.alert_id)
            return EvaluateAlertResult(alert_check_id=None, should_notify=False, new_state=AlertState(alert.state))
        executor = _LLM_EVALUATE_EXECUTOR if uses_llm_detector else None
        # Shielded, so cancelling the attempt leaves this future to complete when the thread exits,
        # which is what _stop_work waits for.
        thread = asyncio.ensure_future(
            database_sync_to_async(_evaluate, thread_sensitive=False, executor=executor)(alert)
        )
        return await asyncio.shield(thread)

    timeouts = alert_timeouts(inputs.calculation_interval)

    def _log_thread_outcome(finished: asyncio.Future[EvaluateAlertResult]) -> None:
        # Retrieve the error the thread ended on, so asyncio does not log it as never retrieved.
        error = None if finished.cancelled() else finished.exception()
        if error is not None and not isinstance(error, (CHQueryErrorQueryWasCancelled, _EvaluationStopped)):
            logger.warning("alerts.evaluate.stopped_thread_failed", alert_id=inputs.alert_id, exc_info=error)

    async def _stop_work() -> bool:
        # Cancellation cannot reach the thread the query runs in, so the query is killed in
        # ClickHouse by the id it was tagged with. A kill only finds a query that is running at that
        # moment, and the thread may still be waiting for a connection or be between two queries, so
        # it is repeated until the thread has exited on the killed query's error. A thread that
        # outlives a whole evaluation budget after that is stuck on something no kill reaches, such
        # as a node that stopped answering, and is abandoned so the slot it kept lapses instead.
        stopping.set()
        if thread is None or team_id is None:
            return True
        thread.add_done_callback(_log_thread_outcome)
        give_up_at = time.monotonic() + timeouts.activity_schedule_to_close.total_seconds()
        while not thread.done() and time.monotonic() < give_up_at:
            try:
                await _run_control(_CANCELLATION_EXECUTOR, cancel_query_on_cluster, team_id, query_id)
            except Exception:
                logger.exception("alerts.evaluate.cancel_query_failed", alert_id=inputs.alert_id)
            await asyncio.wait({thread}, timeout=_SLOT_POLL_SECONDS)
        if not thread.done():
            logger.error("alerts.evaluate.thread_abandoned", alert_id=inputs.alert_id, evaluation_id=evaluation_id)
        return thread.done()

    async with Heartbeater():
        held_until = await _hold_evaluation_slot_before_running(
            inputs.alert_id, lease_seconds=timeouts.evaluation_slot_lease.lease.total_seconds()
        )
    return await _run_holding_slot(
        inputs.alert_id,
        held_until,
        _load_and_evaluate,
        retry_policy=timeouts.evaluate_retry_policy,
        keeps_slot=lambda _result: False,
        lease=timeouts.evaluation_slot_lease,
        stop_work=_stop_work,
    )


def _lock_evaluation_alert(*, alert_id: str, team_id: int, insight_id: int) -> AlertConfiguration | None:
    # Call inside transaction.atomic(). Insight deletion takes the same lock order.
    if not lock_insight_for_evaluation(insight_id=insight_id, team_id=team_id):
        return None
    alert = (
        AlertConfiguration.objects.select_for_update(of=("self",), no_key=True)
        .select_related("insight", "team", "threshold")
        .filter(id=alert_id, team_id=team_id)
        .first()
    )
    if alert is None or alert.insight_id != insight_id:
        return None
    # Threshold is nullable, so PostgreSQL cannot lock it through the outer join.
    if alert.threshold_id is not None:
        alert.threshold = Threshold.objects.select_for_update(no_key=True).get(id=alert.threshold_id, team_id=team_id)
    return alert


def _evaluation_inputs_match(evaluated_fingerprint: str, current: AlertConfiguration) -> bool:
    return evaluated_fingerprint == _evaluation_fingerprint(current)


def _evaluation_fingerprint(alert: AlertConfiguration) -> str:
    fields = (
        "enabled",
        "insight_id",
        "created_by_id",
        "condition",
        "config",
        "detector_config",
        "threshold_id",
        "calculation_interval",
        "next_check_at",
        "skip_weekend",
        "schedule_start_time",
        "schedule_restriction",
        "snoozed_until",
    )
    values = [
        *(getattr(alert, field) for field in fields),
        alert.insight.name,
        alert.insight.query,
        alert.insight.deleted,
        alert.threshold.configuration if alert.threshold else None,
    ]
    return hashlib.sha256(json.dumps(values, cls=DjangoJSONEncoder, sort_keys=True).encode()).hexdigest()


@database_sync_to_async(thread_sensitive=False)
def _load_alert_for_evaluation(inputs: EvaluateAlertActivityInputs) -> AlertConfiguration:
    queryset = AlertConfiguration.objects.select_related("insight", "team", "threshold")
    if inputs.team_id is not None:
        queryset = queryset.filter(team_id=inputs.team_id)
    try:
        alert = queryset.get(id=inputs.alert_id)
    except AlertConfiguration.DoesNotExist:
        raise ApplicationError(
            f"Alert {inputs.alert_id} not found between prepare and evaluate",
            non_retryable=True,
        )
    if not alert.enabled:
        raise ApplicationError(
            f"Alert {inputs.alert_id} disabled between prepare and evaluate",
            non_retryable=True,
        )
    return alert


@temporalio.activity.defn
async def record_failed_evaluation(inputs: RecordFailedEvaluationActivityInputs) -> RecordFailedEvaluationResult:
    """Persist an errored AlertCheck for an evaluation that never got to write one itself.

    evaluate_alert re-raises transient ClickHouse errors so its retry policy can get past a busy
    cluster. Nothing has written an AlertCheck by the time those attempts run out, and next_check_at
    is still in the past, so the one-minute sweep would start the whole chain over again: an alert
    whose query fails every time would run forever, and its owner would never be told. Recording the
    failure here advances next_check_at to the alert's normal cadence slot, which caps a permanently
    failing alert at one chain of attempts per cadence period.
    """

    @database_sync_to_async(thread_sensitive=False)
    def _record() -> RecordFailedEvaluationResult:
        try:
            queryset = AlertConfiguration.objects.all()
            if inputs.team_id is not None:
                queryset = queryset.filter(team_id=inputs.team_id)
            snapshot = queryset.only("team_id", "insight_id").get(id=inputs.alert_id)
            with transaction.atomic():
                alert = _lock_evaluation_alert(
                    alert_id=inputs.alert_id,
                    team_id=snapshot.team_id,
                    insight_id=snapshot.insight_id,
                )
                if alert is None or (
                    inputs.evaluation_fingerprint is not None
                    and inputs.evaluation_fingerprint != _evaluation_fingerprint(alert)
                ):
                    return RecordFailedEvaluationResult()
                # Disabling an alert mid-check makes evaluate_alert raise a non-retryable "disabled
                # between prepare and evaluate" error into this path. That is a normal user action,
                # not an alert failure, so it must not gain an errored check or email subscribers.
                if not alert.enabled:
                    logger.info("alerts.skip_failed_evaluation_disabled", alert_id=inputs.alert_id)
                    return RecordFailedEvaluationResult()
                # add_alert_check advances next_check_at, so skipping once it is in the future keeps a
                # committed-but-undelivered retry from writing a duplicate errored check. Best effort:
                # a real-time alert lagging past its short cadence can still write one, but the state
                # machine keeps that from sending a duplicate notification.
                if alert.next_check_at is not None and alert.next_check_at > datetime.now(UTC):
                    return RecordFailedEvaluationResult()
                error = _failed_evaluation_error(inputs)
                alert_check, should_notify = _write_errored_alert_check(
                    alert, error, is_transient_error=_is_transient_failure(inputs)
                )
        except AlertConfiguration.DoesNotExist:
            logger.warning("Alert gone before its failure could be recorded", alert_id=inputs.alert_id)
            return RecordFailedEvaluationResult()

        # Counted here and not on the failing attempt, so one scheduled check stays one increment
        # however many times Temporal retried it.
        if error.get("code") == LLM_DETECTOR_UNAVAILABLE_ERROR_CODE:
            record_ai_detector_check_outcome("unavailable")

        logger.warning(
            "alerts.recorded_failed_evaluation",
            alert_id=inputs.alert_id,
            alert_check_id=str(alert_check.id),
            error_type=inputs.error_type,
        )
        return RecordFailedEvaluationResult(alert_check_id=str(alert_check.id), should_notify=should_notify)

    async with Heartbeater():
        return await _record()


def dispatch_alert_firing_realtime_notification(
    alert: AlertConfiguration, alert_check: AlertCheck, breaches: list[str]
) -> None:
    """Fan out one realtime in-app notification per subscribed user when an alert fires.

    Exceptions are caught and logged internally so a realtime delivery failure does not
    poison the email path or the alert-check transaction.
    """
    try:
        body = "; ".join(breaches[:3])
        if len(breaches) > 3:
            body += f" (+{len(breaches) - 3} more)"
        title = f"Alert firing: {alert.name}"[:100]
        source_url = f"/project/{alert.team.project_id}/insights/{alert.insight.short_id}#alert={alert.id}"
        for user_id in alert.subscribed_users.values_list("id", flat=True):
            create_notification(
                NotificationData(
                    team_id=alert.team_id,
                    notification_type=NotificationType.ALERT_FIRING,
                    priority=Priority.NORMAL,
                    title=title,
                    body=body,
                    target_type=TargetType.USER,
                    target_id=str(user_id),
                    resource_type="insight",
                    resource_id=str(alert.insight.short_id),
                    source_url=source_url,
                    source_type=SourceType.INSIGHT,
                    source_id=str(alert.insight.short_id),
                    # A dispatch that accepted nothing leaves targets_notified empty, so a
                    # retried activity reaches this again; dedupe here rather than on that.
                    idempotency_key=f"alert-firing:{alert_check.id}:{user_id}",
                )
            )
    except Exception:
        logger.exception("alerts.realtime_notification_failed", alert_id=str(alert.id))


def dispatch_alert_error_in_app_notifications(alert: AlertConfiguration, alert_check: AlertCheck) -> None:
    """Create one best-effort in-app notification per eligible recipient for an errored check."""
    error = alert_check.error if isinstance(alert_check.error, dict) else {}
    error_message = str(error.get("message") or "Unknown error").strip().rstrip(".")[:1000] or "Unknown error"
    alert_name = alert.name or "Alert"
    source_url = f"/project/{alert.team_id}/insights/{alert.insight.short_id}?alert_id={alert.id}"
    error_code = error.get("code")
    if error_code == "invalid_configuration":
        # The check turned the alert off, so a promise to try again would be false.
        title = f"{alert_name[:75]} was turned off"
        body = (
            f"PostHog turned this alert off because it could not be evaluated: {error_message}. "
            "Fix the alert or insight settings, then turn the alert back on."
        )
    else:
        next_check_at = next_scheduled_check_time(alert)
        next_check_message = (
            f"PostHog will try again on {next_check_at}."
            if next_check_at
            else "PostHog will try again at the next scheduled check."
        )
        title = f"{alert_name[:75]} could not be evaluated"
        if error_code == LLM_DETECTOR_UNAVAILABLE_ERROR_CODE:
            # A check the AI detector could not complete is not something the owner can fix,
            # so this case drops the advice to review the alert settings.
            body = (
                f"PostHog could not evaluate this alert: {error_message}. "
                f"{next_check_message} If it fails again, contact support."
            )
        else:
            body = (
                f"PostHog could not evaluate this alert: {error_message}. "
                "This can happen when the insight or alert settings need attention, or when PostHog has a "
                f"temporary problem. Review the alert settings. {next_check_message} If it fails again, "
                "contact support."
            )

    for user_id, _ in get_alert_error_notification_recipients(alert):
        try:
            create_notification(
                NotificationData(
                    team_id=alert.team_id,
                    notification_type=NotificationType.PIPELINE_FAILURE,
                    priority=Priority.NORMAL,
                    title=title,
                    body=body,
                    target_type=TargetType.USER,
                    target_id=str(user_id),
                    resource_type="insight",
                    resource_id=str(alert.insight.short_id),
                    source_url=source_url,
                    source_type=None,
                    source_id=str(alert_check.id),
                    idempotency_key=f"alert-evaluation-failure:{alert_check.id}:{user_id}",
                )
            )
        except Exception:
            logger.exception(
                "alerts.error_realtime_notification_failed",
                alert_id=str(alert.id),
                alert_check_id=str(alert_check.id),
                user_id=user_id,
            )


# Idempotency: empty targets_notified = not yet delivered; non-empty = already delivered.
# Lets Temporal retry notify_alert safely after a transient failure past the send.
@temporalio.activity.defn
async def notify_alert(inputs: NotifyAlertActivityInputs) -> None:
    """Send notifications for a previously evaluated alert check (idempotent)."""

    @database_sync_to_async(thread_sensitive=False, executor=_NOTIFICATION_DELIVERY_EXECUTOR)
    def _notify() -> None:
        # Mismatched pair surfaces as DoesNotExist instead of notifying the wrong alert.
        alert_check = AlertCheck.objects.select_related(
            "alert_configuration", "alert_configuration__team", "alert_configuration__insight"
        ).get(
            pk=inputs.alert_check_id,
            alert_configuration_id=inputs.alert_id,
        )

        if alert_check.targets_notified:
            logger.info(
                "notify_alert: already notified, skipping",
                alert_id=inputs.alert_id,
                alert_check_id=alert_check.id,
            )
            return

        alert = alert_check.alert_configuration

        # Raises if FIRING with no breaches; caller (workflow) must pipe breaches from evaluate.
        deliveries = dispatch_alert_notification(alert, alert_check, inputs.breaches)
        if deliveries is None:
            return

        with transaction.atomic():
            # Writes the sentinel + notification_sent_at together — the investigation
            # workflow and safety-net read that column to decide whether they still
            # need to dispatch, and the gating path relies on it for idempotency.
            record_alert_delivery(alert, alert_check, deliveries)

        # Both in-app paths dedupe on their own idempotency key, so neither depends on
        # record_alert_delivery having written the sentinel.
        if alert_check.state == AlertState.FIRING.value and inputs.breaches:
            dispatch_alert_firing_realtime_notification(alert, alert_check, inputs.breaches)
        elif alert_check.state == AlertState.ERRORED.value:
            dispatch_alert_error_in_app_notifications(alert, alert_check)

    async with Heartbeater():
        await _notify()


@temporalio.activity.defn
async def run_investigation_safety_net() -> int:
    """Force-dispatch notifications for gated AlertChecks whose investigation stalled.

    Returns the number of checks that were force-notified (for metrics / tests).
    """

    @database_sync_to_async(thread_sensitive=False)
    def _sweep() -> int:
        return run_investigation_notification_safety_net()

    async with Heartbeater():
        return await _sweep()


@temporalio.activity.defn
async def cleanup_alert_checks() -> int:
    @database_sync_to_async(thread_sensitive=False)
    def _cleanup() -> int:
        return AlertCheck.clean_up_old_checks()

    async with Heartbeater():
        return await _cleanup()

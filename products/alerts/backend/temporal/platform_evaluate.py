"""Temporal wiring for the platform's parallel insight evaluation.

The decisions live in `products/alerts/backend/platform_source_cycle.py`, so they stay plain
functions a test can call without Temporal.

One activity per admitted check, run side by side. A batch key is a team's alerts due in one
minute, and daily alerts in one timezone share their minute, so evaluating a key one check after
another would put the last check minutes behind the first.
"""

import time
import asyncio
import datetime as dt
from collections.abc import Callable
from dataclasses import replace

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from django.conf import settings

    from posthog.schema_enums import AlertCalculationInterval
    from posthog.temporal.alerts.retry_policy import alert_timeouts
    from posthog.temporal.common.errors import (
        MAX_ERROR_MESSAGE_CHARS,
        truncate_for_temporal_payload,
        unwrap_temporal_cause,
    )
    from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
    from posthog.temporal.common.utils import close_db_connections

    from products.alerts.backend.platform_chart_detail import RenderedChart, pending_chart_alert_id, with_chart
    from products.alerts_platform.backend.facade.contracts import (
        RECORD_OUTCOMES_ACTIVITY,
        AlertDeliveryRequest,
        PlatformAlertOutcome,
        SourceBatchEvaluation,
        SourceEvaluationInputs,
        SourceKind,
        SourceOutcomeInputs,
    )
    from products.alerts_platform.backend.facade.payload import outcome_chunks
    from products.alerts_platform.backend.facade.platform_metrics import increment_checks_unfinished, safe_record
    from products.alerts_platform.backend.facade.temporal import source_evaluation_timeout, start_deliveries

PLAN_START_TO_CLOSE = dt.timedelta(seconds=10)
PLAN_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=20)
# Production's per-attempt budget for an hourly or slower check, so a query the parallel run
# gives up on is one production would have given up on as well.
CHECK_START_TO_CLOSE = alert_timeouts(None).evaluate_start_to_close
# Checks wait for a worker slot here. Derived rather than set, so queue time cannot shorten a
# check below its own budget.
CHECK_QUEUE_TOLERANCE = dt.timedelta(minutes=1)
CHECK_SCHEDULE_TO_CLOSE = CHECK_START_TO_CLOSE + CHECK_QUEUE_TOLERANCE
# Production's real-time budget: a shorter attempt, and one retry inside the same total.
_REAL_TIME_TIMEOUTS = alert_timeouts(AlertCalculationInterval.REAL_TIME)
REAL_TIME_CHECK_START_TO_CLOSE = _REAL_TIME_TIMEOUTS.evaluate_start_to_close
REAL_TIME_CHECK_SCHEDULE_TO_CLOSE = _REAL_TIME_TIMEOUTS.activity_schedule_to_close + CHECK_QUEUE_TOLERANCE
REAL_TIME_CHECK_RETRY_POLICY = _REAL_TIME_TIMEOUTS.evaluate_retry_policy
# Production's real-time heartbeat, so a check whose worker died is retried inside its budget.
REAL_TIME_CHECK_HEARTBEAT_TIMEOUT = _REAL_TIME_TIMEOUTS.heartbeat_timeout
# Production's retries for an AI detector check, inside the default budget. A judge that reaches
# no verdict raises for another attempt, and the last attempt records the failure.
LLM_CHECK_RETRY_POLICY = alert_timeouts(None).evaluate_retry_policy
# A firing's chart renders in its own activity, after the check has released its pool slot. It
# outlasts the export render's own 90-second limit, so the render, not the activity, gives up first.
CHART_START_TO_CLOSE = dt.timedelta(minutes=2)
# Room to wait for a render slot. A render that gets none in time sends its firing without a chart.
CHART_SCHEDULE_TO_CLOSE = CHART_START_TO_CLOSE + dt.timedelta(minutes=2)
CHART_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=dt.timedelta(seconds=30),
)
FAIL_START_TO_CLOSE = dt.timedelta(seconds=10)
FAIL_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=20)
# Stopping a query can wait on a slow ClickHouse, so it runs apart from the failed check's record
# and never holds it back. It is best effort, so it gets what the batch budget leaves.
STOP_QUERIES_START_TO_CLOSE = dt.timedelta(seconds=60)
RECORD_START_TO_CLOSE = dt.timedelta(seconds=8)
RECORD_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=12)
# The pool admits once per round, so a batch that admits only once evaluates at most one pool of
# checks per tick. Rounds refill the slots that finished checks free, the way production's
# scheduler does, until this budget ends. It stays under the one-minute tick.
ADMISSION_RUN_BUDGET = dt.timedelta(seconds=50)
ADMISSION_POLL_INTERVAL = dt.timedelta(seconds=2)
# What the source needs from its binding's `evaluation_timeout`. The checks run side by side, so
# the batch costs the admission rounds plus one check's budget, not one per check. The last check
# can end while an earlier record still runs, so the tail holds two records and their failures,
# or one record and the stop of a failed check's queries.
EVALUATION_BUDGET = (
    PLAN_SCHEDULE_TO_CLOSE
    + ADMISSION_RUN_BUDGET
    + max(CHECK_SCHEDULE_TO_CLOSE, REAL_TIME_CHECK_SCHEDULE_TO_CLOSE)
    + max(CHART_SCHEDULE_TO_CLOSE, FAIL_SCHEDULE_TO_CLOSE)
    + RECORD_SCHEDULE_TO_CLOSE
    + max(FAIL_SCHEDULE_TO_CLOSE + RECORD_SCHEDULE_TO_CLOSE, STOP_QUERIES_START_TO_CLOSE)
)
_PATCH_READMISSION = "platform-insight-readmission-2026-10"
# Runs started before it recorded every outcome in one activity, and replay must schedule the same.
_PATCH_CHUNKED_RECORD = "platform-insight-chunked-record-2026-10"
# Runs started before it planned bare ids, and gave every check the default budget.
_PATCH_CHECK_BUDGETS = "platform-insight-check-budgets-2026-10"
# Runs started before it evaluated every check on this queue. A plan can return an AI detector
# check into such a run during a deploy, and replay must schedule the activity that run recorded.
_PATCH_AI_DETECTOR_QUEUE = "platform-insight-ai-detector-queue-2026-10"
# Runs started before it rendered charts inside the check, and replay must not schedule a render.
_PATCH_CHART_AFTER_CHECK = "platform-insight-chart-after-check-2026-10"
# Runs started before it recorded every outcome once the whole batch ended, and failed checks left none.
_PATCH_RECORD_AS_FINISHED = "platform-insight-record-as-finished-2026-10"
# Runs started before it returned when their first round found the pool full, and replay must not poll.
_PATCH_WAIT_FOR_POOL = "platform-insight-wait-for-pool-2026-10"


@frozen
class InsightBatchPlanInputs:
    evaluation: SourceEvaluationInputs
    expires_at: float
    exclude: tuple[str, ...] = ()


@frozen
class AdmittedInsightCheck:
    """An admitted check, with what the workflow needs to give it production's budget."""

    configuration_id: str
    real_time: bool = False
    uses_llm_detector: bool = False
    # The platform owns the alert, so this check is the one that notifies.
    owned_by_platform: bool = False


@frozen
class InsightChartInputs:
    team_id: int
    alert_id: str


@frozen
class InsightCheckInputs:
    evaluation: SourceEvaluationInputs
    configuration_id: str
    held_until: float
    # The worker this check was routed to. Only the AI queue's worker holds the model credentials.
    uses_llm_detector: bool = False
    owned_by_platform: bool = False


@frozen
class FailedInsightCheckInputs:
    evaluation: SourceEvaluationInputs
    configuration_id: str
    error_message: str
    error_type: str | None = None


@frozen
class StopInsightQueriesInputs:
    team_id: int
    configuration_id: str
    # The queries a failed check's attempts ran under, any of which may still run.
    query_ids: tuple[str, ...]


@activity.defn
@close_db_connections
def plan_platform_insight_batch_activity(inputs: InsightBatchPlanInputs) -> list[str]:
    # Imported in the body: the workflow below forces this module to evaluate inside Temporal's
    # sandbox, which a Django model import trips.
    from products.alerts.backend.platform_source_cycle import plan_insight_batch  # noqa: PLC0415

    key = inputs.evaluation.batch_key
    return list(
        plan_insight_batch(
            key.team_id,
            key.slot,
            dt.datetime.fromisoformat(inputs.evaluation.cutoff),
            expires_at=inputs.expires_at,
            exclude=inputs.exclude,
        )
    )


@activity.defn
@close_db_connections
def plan_platform_insight_round_activity(inputs: InsightBatchPlanInputs) -> list[str]:
    """`plan_platform_insight_batch_activity` with `exclude`, under its own name. A worker still on
    the old code runs the old name and drops `exclude`, so the round path must not call that name."""
    from products.alerts.backend.platform_source_cycle import plan_insight_batch  # noqa: PLC0415

    key = inputs.evaluation.batch_key
    return list(
        plan_insight_batch(
            key.team_id,
            key.slot,
            dt.datetime.fromisoformat(inputs.evaluation.cutoff),
            expires_at=inputs.expires_at,
            exclude=inputs.exclude,
        )
    )


@activity.defn
@close_db_connections
def plan_platform_insight_checks_activity(inputs: InsightBatchPlanInputs) -> list[AdmittedInsightCheck]:
    """`plan_platform_insight_round_activity` with each check's cadence, under its own name, because
    a run that recorded the old name must decode bare ids on replay."""
    from products.alerts.backend.llm_detector_limits import is_llm_detector_config  # noqa: PLC0415
    from products.alerts.backend.platform_source_cycle import legacy_alerts_of, plan_insight_batch  # noqa: PLC0415

    key = inputs.evaluation.batch_key
    cutoff = dt.datetime.fromisoformat(inputs.evaluation.cutoff)
    admitted = plan_insight_batch(key.team_id, key.slot, cutoff, expires_at=inputs.expires_at, exclude=inputs.exclude)
    alerts = legacy_alerts_of(key.team_id, key.slot, cutoff, admitted)
    checks: list[AdmittedInsightCheck] = []
    for configuration_id in admitted:
        alert = alerts.get(configuration_id)
        checks.append(
            AdmittedInsightCheck(
                configuration_id=configuration_id,
                real_time=alert is not None and alert.calculation_interval == AlertCalculationInterval.REAL_TIME,
                uses_llm_detector=alert is not None and is_llm_detector_config(alert.detector_config),
                owned_by_platform=alert is not None and alert.platform_owned,
            )
        )
    return checks


def _evaluate_check(
    inputs: InsightCheckInputs, info: activity.Info, *, final_attempt: bool
) -> SourceBatchEvaluation | None:
    from products.alerts.backend.platform_source_cycle import (  # noqa: PLC0415
        evaluate_insight_check,
        readmit_retried_check,
    )

    key = inputs.evaluation.batch_key
    held_until: float | None = inputs.held_until
    if info.attempt > 1:
        held_until = readmit_retried_check(
            key.team_id,
            inputs.configuration_id,
            previous_query_id=f"{info.workflow_run_id}:{info.activity_id}:{info.attempt - 1}",
            held_until=inputs.held_until,
            attempt=info.attempt,
        )
    if held_until is None:
        # No outcome keeps the check due, so a later tick evaluates it once the pool has room.
        return None
    return evaluate_insight_check(
        key.team_id,
        key.slot,
        dt.datetime.fromisoformat(inputs.evaluation.cutoff),
        inputs.configuration_id,
        held_until=held_until,
        evaluation_id=f"{info.workflow_run_id}:{info.activity_id}",
        attempt=info.attempt,
        final_attempt=final_attempt,
        uses_llm_detector=inputs.uses_llm_detector,
    )


@activity.defn
@close_db_connections
def evaluate_platform_insight_check_activity(inputs: InsightCheckInputs) -> SourceBatchEvaluation | None:
    """Sync, so the thread this blocks is a slot Temporal is accounting for. Heartbeats only when the
    workflow set a heartbeat timeout."""
    with HeartbeaterSync():
        return _evaluate_check(inputs, activity.info(), final_attempt=True)


@activity.defn
@close_db_connections
def fail_platform_insight_check_activity(inputs: FailedInsightCheckInputs) -> SourceBatchEvaluation | None:
    """The errored outcome of a check whose every attempt ended without one."""
    from products.alerts.backend.platform_source_cycle import fail_insight_check  # noqa: PLC0415

    key = inputs.evaluation.batch_key
    return fail_insight_check(
        key.team_id,
        key.slot,
        dt.datetime.fromisoformat(inputs.evaluation.cutoff),
        inputs.configuration_id,
        error_message=inputs.error_message,
        error_type=inputs.error_type,
    )


@activity.defn
@close_db_connections
def stop_platform_insight_queries_activity(inputs: StopInsightQueriesInputs) -> None:
    """Stops the queries a failed check's attempts may still run, because a timed-out attempt's
    thread keeps its query going."""
    from products.alerts.backend.platform_source_cycle import stop_insight_queries  # noqa: PLC0415

    stop_insight_queries(inputs.team_id, inputs.configuration_id, inputs.query_ids)


@activity.defn
@close_db_connections
async def evaluate_platform_insight_llm_check_activity(inputs: InsightCheckInputs) -> SourceBatchEvaluation | None:
    """An AI detector check. It runs on the AI queue, because only that worker holds the model
    credentials, on the pool production's AI checks use, so the worker never runs more checks than
    the judge has model-call slots. `PLATFORM_LLM_CHECKS` caps how many of its threads a parallel
    check takes. A check of an alert the platform owns is production's own, so it skips that cap,
    as production's checks do."""
    from posthog.sync import database_sync_to_async  # noqa: PLC0415

    from products.alerts.backend.judge.executor import LLM_EVALUATE_EXECUTOR  # noqa: PLC0415
    from products.alerts.backend.platform_source_cycle import PLATFORM_LLM_CHECKS  # noqa: PLC0415

    info = activity.info()
    evaluate = database_sync_to_async(_evaluate_check, thread_sensitive=False, executor=LLM_EVALUATE_EXECUTOR)
    final_attempt = info.attempt >= LLM_CHECK_RETRY_POLICY.maximum_attempts
    if inputs.owned_by_platform:
        return await evaluate(inputs, info, final_attempt=final_attempt)
    await PLATFORM_LLM_CHECKS.acquire()
    thread = asyncio.ensure_future(evaluate(inputs, info, final_attempt=final_attempt))
    thread.add_done_callback(_release_platform_llm_check)
    # Shielded, so a cancelled attempt leaves the thread holding its place in the cap until it ends.
    return await asyncio.shield(thread)


def _release_platform_llm_check(thread: "asyncio.Future[SourceBatchEvaluation | None]") -> None:
    from products.alerts.backend.platform_source_cycle import PLATFORM_LLM_CHECKS  # noqa: PLC0415

    PLATFORM_LLM_CHECKS.release()
    # Read the error of a thread nobody awaits any more, so asyncio does not log it as never retrieved.
    if not thread.cancelled():
        thread.exception()


@activity.defn
@close_db_connections
def render_platform_insight_chart_activity(inputs: InsightChartInputs) -> RenderedChart | None:
    """Sync, because the render blocks for its whole duration. Only a full render pool raises, for a
    retry. Any other failure sends the firing without a chart, as production does."""
    from products.alerts.backend.platform_source_cycle import ChartRenderPoolFull, render_firing_chart  # noqa: PLC0415

    try:
        # A slot of its own per attempt, so a timed-out attempt cannot release its retry's slot.
        return render_firing_chart(
            inputs.team_id, inputs.alert_id, held_until=time.time() + CHART_START_TO_CLOSE.total_seconds()
        )
    except ChartRenderPoolFull:
        raise
    except Exception:
        activity.logger.exception(
            "Could not render a platform insight firing's chart", extra={"alert_id": inputs.alert_id}
        )
        return None


@workflow.defn(name="insight-alert-platform-evaluate")
class InsightAlertPlatformEvaluateWorkflow(PostHogWorkflow):
    """Evaluates one batch key, records what it decided, and starts the deliveries its checks asked
    for. Only the alerts the insight source allowlists ask for one."""

    inputs_cls = SourceEvaluationInputs

    @workflow.run
    async def run(self, inputs: SourceEvaluationInputs) -> int:
        # From the workflow's clock, so a retried plan reuses the expiry and gets its slots back. A
        # check releases its slot only while the slot still carries this expiry.
        expires_at = (workflow.now() + source_evaluation_timeout(SourceKind.INSIGHT)).timestamp()
        if workflow.patched(_PATCH_READMISSION) and workflow.patched(_PATCH_RECORD_AS_FINISHED):
            return await self._evaluate_and_record_in_rounds(inputs, expires_at)
        if workflow.patched(_PATCH_READMISSION):
            settled = await self._evaluate_in_rounds(inputs, expires_at)
        else:
            admitted = await self._plan(
                inputs, expires_at, exclude=(), activity_fn=plan_platform_insight_batch_activity
            )
            settled = await asyncio.gather(
                *(
                    self._check(inputs, AdmittedInsightCheck(configuration_id=configuration_id), expires_at)
                    for configuration_id in admitted
                ),
                return_exceptions=True,
            )
        if not settled:
            return 0

        for result in settled:
            # Only a check's own failure is a missing outcome. A cancellation or a bug in this
            # workflow would otherwise be recorded as a partial batch.
            if isinstance(result, BaseException) and not isinstance(result, ActivityError):
                raise result
        evaluations = [result for result in settled if isinstance(result, SourceBatchEvaluation)]
        if workflow.patched(_PATCH_CHART_AFTER_CHECK):
            evaluations = await self._with_charts(inputs, evaluations)
        # A check that ran on new code under a run that started before the patch leaves its marker.
        evaluations = [with_chart(evaluation, None) for evaluation in evaluations]
        outcomes = tuple(outcome for evaluation in evaluations for outcome in evaluation.outcomes)
        if len(outcomes) < len(settled):
            workflow.logger.warning(
                "%d of %d platform insight checks reached no outcome", len(settled) - len(outcomes), len(settled)
            )
            safe_record(increment_checks_unfinished, SourceKind.INSIGHT.value, len(settled) - len(outcomes))
        if not outcomes:
            return 0
        await self._record(inputs, evaluations, chunked=workflow.patched(_PATCH_CHUNKED_RECORD))
        return len(outcomes)

    async def _with_charts(
        self, inputs: SourceEvaluationInputs, evaluations: list[SourceBatchEvaluation]
    ) -> list[SourceBatchEvaluation]:
        """Renders each firing's chart side by side. A render that fails leaves its firing without one,
        as production sends a firing without its chart."""
        pending = [pending_chart_alert_id(evaluation) for evaluation in evaluations]
        rendered = await asyncio.gather(
            *(
                workflow.execute_activity(
                    render_platform_insight_chart_activity,
                    InsightChartInputs(team_id=inputs.batch_key.team_id, alert_id=alert_id),
                    start_to_close_timeout=CHART_START_TO_CLOSE,
                    schedule_to_close_timeout=CHART_SCHEDULE_TO_CLOSE,
                    retry_policy=CHART_RETRY_POLICY,
                )
                for alert_id in pending
                if alert_id is not None
            ),
            return_exceptions=True,
        )
        charts = iter(rendered)
        result: list[SourceBatchEvaluation] = []
        for evaluation, alert_id in zip(evaluations, pending):
            if alert_id is None:
                result.append(evaluation)
                continue
            chart = next(charts)
            if isinstance(chart, BaseException) and not isinstance(chart, ActivityError):
                raise chart
            result.append(with_chart(evaluation, chart if isinstance(chart, RenderedChart) else None))
        return result

    async def _plan(
        self,
        inputs: SourceEvaluationInputs,
        expires_at: float,
        *,
        exclude: tuple[str, ...],
        activity_fn: Callable[[InsightBatchPlanInputs], list[str]],
    ) -> list[str]:
        return await workflow.execute_activity(
            activity_fn,
            InsightBatchPlanInputs(evaluation=inputs, expires_at=expires_at, exclude=exclude),
            start_to_close_timeout=PLAN_START_TO_CLOSE,
            schedule_to_close_timeout=PLAN_SCHEDULE_TO_CLOSE,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _check(
        self, inputs: SourceEvaluationInputs, admitted: AdmittedInsightCheck, expires_at: float
    ) -> SourceBatchEvaluation | None:
        check_inputs = InsightCheckInputs(
            evaluation=inputs,
            configuration_id=admitted.configuration_id,
            held_until=expires_at,
            owned_by_platform=admitted.owned_by_platform,
        )
        if admitted.uses_llm_detector and workflow.patched(_PATCH_AI_DETECTOR_QUEUE):
            return await workflow.execute_activity(
                evaluate_platform_insight_llm_check_activity,
                replace(check_inputs, uses_llm_detector=True),
                task_queue=settings.MAX_AI_TASK_QUEUE,
                start_to_close_timeout=CHECK_START_TO_CLOSE,
                schedule_to_close_timeout=CHECK_SCHEDULE_TO_CLOSE,
                retry_policy=LLM_CHECK_RETRY_POLICY,
            )
        if admitted.real_time:
            return await workflow.execute_activity(
                evaluate_platform_insight_check_activity,
                check_inputs,
                start_to_close_timeout=REAL_TIME_CHECK_START_TO_CLOSE,
                schedule_to_close_timeout=REAL_TIME_CHECK_SCHEDULE_TO_CLOSE,
                heartbeat_timeout=REAL_TIME_CHECK_HEARTBEAT_TIMEOUT,
                retry_policy=REAL_TIME_CHECK_RETRY_POLICY,
            )
        # One attempt each. In a run that records as checks finish, a check that does not finish is
        # recorded as errored. In an older run it leaves no outcome and keeps its due time.
        return await workflow.execute_activity(
            evaluate_platform_insight_check_activity,
            check_inputs,
            start_to_close_timeout=CHECK_START_TO_CLOSE,
            schedule_to_close_timeout=CHECK_SCHEDULE_TO_CLOSE,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    async def _plan_round(
        self, inputs: SourceEvaluationInputs, expires_at: float, *, exclude: tuple[str, ...], budgeted: bool
    ) -> list[AdmittedInsightCheck]:
        if budgeted:
            return await workflow.execute_activity(
                plan_platform_insight_checks_activity,
                InsightBatchPlanInputs(evaluation=inputs, expires_at=expires_at, exclude=exclude),
                start_to_close_timeout=PLAN_START_TO_CLOSE,
                schedule_to_close_timeout=PLAN_SCHEDULE_TO_CLOSE,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        admitted = await self._plan(
            inputs, expires_at, exclude=exclude, activity_fn=plan_platform_insight_round_activity
        )
        return [AdmittedInsightCheck(configuration_id=configuration_id) for configuration_id in admitted]

    async def _evaluate_in_rounds(
        self, inputs: SourceEvaluationInputs, expires_at: float
    ) -> list[SourceBatchEvaluation | None | BaseException]:
        """Admits and starts checks in rounds until a round adds nothing and none of this batch's
        checks still run, or until the admission budget ends."""
        started: dict[str, asyncio.Task[SourceBatchEvaluation | None]] = {}
        deadline = workflow.now() + ADMISSION_RUN_BUDGET
        budgeted = workflow.patched(_PATCH_CHECK_BUDGETS)
        while True:
            try:
                admitted = await self._plan_round(inputs, expires_at, exclude=tuple(started), budgeted=budgeted)
            except ActivityError:
                if not started:
                    raise
                # The started checks still record. Their outcomes are lost if this failure ends the run.
                workflow.logger.warning("Stopped admitting platform insight checks after a failed plan")
                break
            for check in admitted:
                started[check.configuration_id] = asyncio.create_task(self._check(inputs, check, expires_at))
            running = [task for task in started.values() if not task.done()]
            if not running or workflow.now() >= deadline:
                break
            await asyncio.wait(
                running, timeout=ADMISSION_POLL_INTERVAL.total_seconds(), return_when=asyncio.FIRST_COMPLETED
            )
        return await asyncio.gather(*started.values(), return_exceptions=True)

    async def _evaluate_and_record_in_rounds(self, inputs: SourceEvaluationInputs, expires_at: float) -> int:
        """`_evaluate_in_rounds`, but the checks that ended are recorded and delivered at each poll, so
        a slow check in the batch never holds back another's state, schedule or delivery. A check
        whose every attempt failed is recorded as errored. Returns how many outcomes it recorded.

        One record per poll rather than per check, because each record is a transaction and a
        ClickHouse insert of its own. A record that fails keeps its outcomes for the next poll, so a
        passing storage failure does not cost the checks still running.
        """
        started: dict[str, AdmittedInsightCheck] = {}
        unrecorded: dict[str, asyncio.Task[SourceBatchEvaluation | None]] = {}
        waiting: list[SourceBatchEvaluation] = []
        stopping: list[asyncio.Task[None]] = []
        recorded = 0
        admitting = True
        deadline = workflow.now() + ADMISSION_RUN_BUDGET
        next_record_at = workflow.now()
        while True:
            added = False
            if admitting:
                try:
                    admitted = await self._plan_round(inputs, expires_at, exclude=tuple(started), budgeted=True)
                except ActivityError:
                    if not started:
                        raise
                    workflow.logger.warning("Stopped admitting platform insight checks after a failed plan")
                    admitting = False
                else:
                    added = bool(admitted)
                    for check in admitted:
                        started[check.configuration_id] = check
                        unrecorded[check.configuration_id] = asyncio.create_task(
                            self._check_and_chart(inputs, check, expires_at)
                        )
            finished = {configuration_id: task for configuration_id, task in unrecorded.items() if task.done()}
            if (finished or waiting) and (
                workflow.now() >= next_record_at or all(task.done() for task in unrecorded.values())
            ):
                next_record_at = workflow.now() + ADMISSION_POLL_INTERVAL
                for configuration_id in finished:
                    del unrecorded[configuration_id]
                waiting.extend(
                    await self._evaluations_of(
                        inputs,
                        {started[configuration_id]: task for configuration_id, task in finished.items()},
                        stopping,
                    )
                )
                recorded += await self._record_waiting(inputs, waiting, last_chance=False)
            if workflow.now() >= deadline:
                admitting = False
            if not unrecorded:
                # The checks a round added can end while earlier ones record, and free slots for more.
                if admitting and added:
                    continue
                # A batch that has no slot yet found the pool full. Other batches free slots within
                # seconds, so it polls for one rather than leave its checks to a later tick.
                if admitting and not started and workflow.patched(_PATCH_WAIT_FOR_POOL):
                    await workflow.sleep(ADMISSION_POLL_INTERVAL)
                    continue
                recorded += await self._record_waiting(inputs, waiting, last_chance=True)
                await asyncio.gather(*stopping, return_exceptions=True)
                return recorded
            running = [task for task in unrecorded.values() if not task.done()]
            if not running:
                continue
            # While admitting, wake at each poll to refill the pool. After that, wake when a check
            # ends, or when the checks that already ended are due their record. An idle timer would
            # add history events for the whole of a slow check.
            if admitting:
                timeout: float | None = ADMISSION_POLL_INTERVAL.total_seconds()
            elif len(running) < len(unrecorded) or waiting:
                timeout = max((next_record_at - workflow.now()).total_seconds(), 0)
            else:
                timeout = None
            await asyncio.wait(running, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)

    async def _check_and_chart(
        self, inputs: SourceEvaluationInputs, check: AdmittedInsightCheck, expires_at: float
    ) -> SourceBatchEvaluation | None:
        """The check, then its firing's chart, so a slow render holds back only its own check's record.

        No patch guards the render, because a run on this path started on code that renders charts."""
        evaluation = await self._check(inputs, check, expires_at)
        if evaluation is None:
            return None
        return (await self._with_charts(inputs, [evaluation]))[0]

    async def _evaluations_of(
        self,
        inputs: SourceEvaluationInputs,
        finished: dict[AdmittedInsightCheck, "asyncio.Task[SourceBatchEvaluation | None]"],
        stopping: list["asyncio.Task[None]"],
    ) -> list[SourceBatchEvaluation]:
        """What the finished checks decided, with an errored outcome for each check that failed."""
        evaluations: list[SourceBatchEvaluation] = []
        failures: dict[AdmittedInsightCheck, ActivityError] = {}
        for check, task in finished.items():
            error = task.exception()
            if isinstance(error, ActivityError):
                failures[check] = error
            elif error is not None:
                # Only a check's own failure is a missing outcome. A bug in this workflow ends the run.
                raise error
            elif (evaluation := task.result()) is not None:
                evaluations.append(evaluation)
        for check, error in failures.items():
            stopping.append(asyncio.create_task(self._stop_queries(inputs, check, error)))
        failed = await asyncio.gather(*(self._fail(inputs, check, error) for check, error in failures.items()))
        evaluations.extend(evaluation for evaluation in failed if evaluation is not None)
        unfinished = len(finished) - sum(len(evaluation.outcomes) for evaluation in evaluations)
        if unfinished > 0:
            safe_record(increment_checks_unfinished, SourceKind.INSIGHT.value, unfinished)
        return evaluations

    async def _fail(
        self, inputs: SourceEvaluationInputs, check: AdmittedInsightCheck, error: ActivityError
    ) -> SourceBatchEvaluation | None:
        # The reason the owner reads, unwrapped from Temporal's failure and bounded for the payload.
        cause = unwrap_temporal_cause(error)
        message = cause.message if cause is not None else str(error.cause or error)
        try:
            return await workflow.execute_activity(
                fail_platform_insight_check_activity,
                FailedInsightCheckInputs(
                    evaluation=inputs,
                    configuration_id=check.configuration_id,
                    error_message=truncate_for_temporal_payload(message, MAX_ERROR_MESSAGE_CHARS),
                    # Temporal rebuilds a remote error as an ApplicationError carrying the class name on `type`.
                    error_type=cause.type if cause is not None else None,
                ),
                start_to_close_timeout=FAIL_START_TO_CLOSE,
                schedule_to_close_timeout=FAIL_SCHEDULE_TO_CLOSE,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except ActivityError:
            # The check stays due and the next tick evaluates it again, so the batch's other
            # outcomes still record.
            workflow.logger.warning("Could not record a failed platform insight check as errored")
            return None

    async def _stop_queries(
        self, inputs: SourceEvaluationInputs, check: AdmittedInsightCheck, error: ActivityError
    ) -> None:
        # Each attempt queries under `{run}:{activity}:{attempt}`, as `_evaluate_check` names it.
        evaluation_id = f"{workflow.info().run_id}:{error.activity_id}"
        try:
            await workflow.execute_activity(
                stop_platform_insight_queries_activity,
                StopInsightQueriesInputs(
                    team_id=inputs.batch_key.team_id,
                    configuration_id=check.configuration_id,
                    query_ids=tuple(f"{evaluation_id}:{attempt}" for attempt in range(1, _maximum_attempts(check) + 1)),
                ),
                start_to_close_timeout=STOP_QUERIES_START_TO_CLOSE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except ActivityError:
            workflow.logger.warning("Could not stop the queries of a failed platform insight check")

    async def _record_waiting(
        self, inputs: SourceEvaluationInputs, waiting: list[SourceBatchEvaluation], *, last_chance: bool
    ) -> int:
        """Records the waiting outcomes chunk by chunk, and takes each chunk that recorded out of
        `waiting`. A chunk that fails stays for the next poll, unless this is the last chance.
        Returns how many outcomes it recorded."""
        outcomes = tuple(outcome for evaluation in waiting for outcome in evaluation.outcomes)
        deliveries = tuple(delivery for evaluation in waiting for delivery in evaluation.deliveries)
        recorded = 0
        for chunk in outcome_chunks(outcomes) if outcomes else []:
            try:
                await self._record_chunk(inputs, chunk, deliveries)
            except ActivityError:
                if last_chance:
                    raise
                workflow.logger.warning("Will record platform insight outcomes again at the next poll")
                break
            done = {str(outcome.configuration_id) for outcome in chunk}
            waiting[:] = [
                evaluation
                for evaluation in waiting
                if not any(str(outcome.configuration_id) in done for outcome in evaluation.outcomes)
            ]
            recorded += len(chunk)
        return recorded

    async def _record(
        self, inputs: SourceEvaluationInputs, evaluations: list[SourceBatchEvaluation], *, chunked: bool
    ) -> int:
        """Records the outcomes, then starts their deliveries. Returns how many outcomes it recorded."""
        outcomes = tuple(outcome for evaluation in evaluations for outcome in evaluation.outcomes)
        if not outcomes:
            return 0
        deliveries = tuple(delivery for evaluation in evaluations for delivery in evaluation.deliveries)
        for chunk in outcome_chunks(outcomes) if chunked else [outcomes]:
            await self._record_chunk(inputs, chunk, deliveries)
        return len(outcomes)

    async def _record_chunk(
        self,
        inputs: SourceEvaluationInputs,
        chunk: tuple[PlatformAlertOutcome, ...],
        deliveries: tuple[AlertDeliveryRequest, ...],
    ) -> None:
        # Each check's result fits a payload on its own, but the batch's together may not. A chunk's
        # deliveries start after its own record, so a later chunk that fails cannot strand them.
        await workflow.execute_activity(
            RECORD_OUTCOMES_ACTIVITY,
            SourceOutcomeInputs(team_id=inputs.batch_key.team_id, cutoff=inputs.cutoff, outcomes=chunk),
            start_to_close_timeout=RECORD_START_TO_CLOSE,
            schedule_to_close_timeout=RECORD_SCHEDULE_TO_CLOSE,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        # Started only after the record, because a delivery reads the history row the record writes.
        recorded = {str(outcome.configuration_id) for outcome in chunk}
        await start_deliveries([delivery for delivery in deliveries if delivery.configuration_id in recorded])


def _maximum_attempts(check: AdmittedInsightCheck) -> int:
    if check.uses_llm_detector:
        return LLM_CHECK_RETRY_POLICY.maximum_attempts
    if check.real_time:
        return REAL_TIME_CHECK_RETRY_POLICY.maximum_attempts
    return 1


PLATFORM_EVALUATION_WORKFLOWS = [InsightAlertPlatformEvaluateWorkflow]
# Registered on the AI queue's worker, which holds the model credentials.
PLATFORM_AI_QUEUE_ACTIVITIES = [evaluate_platform_insight_llm_check_activity]
PLATFORM_EVALUATION_ACTIVITIES = [
    plan_platform_insight_batch_activity,
    plan_platform_insight_round_activity,
    plan_platform_insight_checks_activity,
    evaluate_platform_insight_check_activity,
    render_platform_insight_chart_activity,
    fail_platform_insight_check_activity,
    stop_platform_insight_queries_activity,
]

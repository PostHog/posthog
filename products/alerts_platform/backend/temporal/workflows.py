import asyncio
import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import replace

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, SearchAttributeKey, WorkflowIDReusePolicy
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    ChildWorkflowError,
    TimeoutError,
    TimeoutType,
    WorkflowAlreadyStartedError,
)

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.errors import NonReportableApplicationError, unwrap_temporal_cause
from posthog.temporal.common.logger import get_write_only_logger

from products.alerts_platform.backend.temporal.metrics import (
    increment_deliveries_previewed,
    increment_discovery_omitted,
    increment_holds_expired,
    record_tick_end,
    record_tick_keys,
    safe_record,
)
from products.alerts_platform.backend.temporal.outcomes import alerts_platform_record_outcomes_activity

LOGGER = get_write_only_logger(__name__)

with workflow.unsafe.imports_passed_through():
    from django.conf import settings
    from django.db import InterfaceError, OperationalError

    from asgiref.sync import sync_to_async

    from posthog.sync import database_sync_to_async_pool
    from posthog.temporal.common.metrics import record_schedule_to_start_latency
    from posthog.temporal.common.schedule import a_describe_schedule

    from products.alerts_platform.backend.delivery.evaluation import deliver_evaluation
    from products.alerts_platform.backend.delivery.thread_store import PENDING_CLAIM_TTL, ThreadBusy
    from products.alerts_platform.backend.facade.contracts import (
        AlertBatchKey,
        AlertDeliveryRequest,
        AlertDemand,
        DemandDiscoveryInputs,
        HeldDeliveryAddress,
        OrchestrateInputs,
        OrchestrateResult,
        SourceDispatchInputs,
        SourceDispatchReport,
        SourceEvaluationInputs,
        TickPage,
    )
    from products.alerts_platform.backend.facade.payload import MAX_BATCH_PAYLOAD_BYTES
    from products.alerts_platform.backend.logic import delivery_holds
    from products.alerts_platform.backend.logic.demand import discover_demand
    from products.alerts_platform.backend.logic.inventory import count_inventory
    from products.alerts_platform.backend.temporal.inventory_metrics import (
        TickScheduleRuns,
        push_inventory,
        push_tick_schedule_runs,
    )
    from products.alerts_platform.backend.temporal.postgres import check_postgres_connection
    from products.alerts_platform.backend.temporal.schedule import SCHEDULE_ID
    from products.alerts_platform.backend.temporal.sources import SOURCE_BINDINGS, discovery_limits


POSTGRES_PROBE_FAILURE = "AlertsPlatformPostgresProbeFailure"
POSTGRES_PROBE_START_TO_CLOSE_TIMEOUT = dt.timedelta(seconds=10)
POSTGRES_PROBE_SCHEDULE_TO_CLOSE_TIMEOUT = dt.timedelta(seconds=30)

# A tick stops starting pages once this much of its minute is spent. The schedule's 50-second
# execution timeout is the backstop, and it spans continued runs.
TICK_DISPATCH_BUDGET = dt.timedelta(seconds=45)
# Evaluations one dispatcher starts before handing the rest back as a later page. Bounds how many
# children a single page opens; the tick's budget decides whether that page gets to run.
MAX_EVALUATIONS_PER_DISPATCH = 50
# Where the hard stop is assumed when the run has no execution timeout of its own.
TICK_HARD_STOP_MARGIN = dt.timedelta(seconds=5)
# A dispatcher gets this long, or the time left before the hard stop, whichever is shorter.
SOURCE_DISPATCH_TIMEOUT = dt.timedelta(seconds=30)
# Time kept between a dispatcher's timeout and the hard stop, so the child closes first.
SOURCE_DISPATCH_HEADROOM = dt.timedelta(seconds=1)
# The noop evaluation's ceiling. A source with an adapter takes its own from its binding.
NOOP_EVALUATION_TIMEOUT = dt.timedelta(seconds=75)

THREAD_BUSY = "AlertsPlatformThreadBusy"
DELIVERY_START_TO_CLOSE = dt.timedelta(seconds=10)
DELIVERY_SCHEDULE_TO_CLOSE = dt.timedelta(seconds=30)
# The workflow waits out a held thread because the activity's retries end inside
# DELIVERY_SCHEDULE_TO_CLOSE, which is shorter than PENDING_CLAIM_TTL. A claim that a dead
# attempt left looks fresh to every one of those retries.
BUSY_RETRY_DELAY = dt.timedelta(seconds=20)
# A delivery run that recorded TRANSITION_EVENTS_PATCH and not NO_TRANSITION_EVENTS_PATCH still
# schedules the emit activity, so its replay matches its history. Once no such run can be open
# (under five minutes per part after the deploy that added NO_TRANSITION_EVENTS_PATCH), delete
# that branch, TRANSITION_EVENTS_PATCH and the activity. Replace the check with
# `workflow.deprecate_patch(NO_TRANSITION_EVENTS_PATCH)`: every newer run carries that marker.
TRANSITION_EVENTS_PATCH = "alerts-platform-transition-events"
NO_TRANSITION_EVENTS_PATCH = "alerts-platform-no-transition-events"
# A dispatcher that started its page one child at a time replays that order. A dispatcher runs for
# at most SOURCE_DISPATCH_TIMEOUT, so a deploy later the sequential branch can go and the check can
# become `workflow.deprecate_patch(CONCURRENT_EVALUATION_STARTS_PATCH)`.
CONCURRENT_EVALUATION_STARTS_PATCH = "alerts-platform-concurrent-evaluation-starts"
# From the first busy result to the start of a later attempt. An attempt that starts this late
# finds every claim the first one saw already stale, so a thread still held is a newer send's.
BUSY_WAIT_LIMIT = PENDING_CLAIM_TTL + BUSY_RETRY_DELAY
# The last attempt can start one attempt and one delay past the limit.
DELIVERY_EXECUTION_TIMEOUT = 3 * DELIVERY_SCHEDULE_TO_CLOSE + BUSY_WAIT_LIMIT + BUSY_RETRY_DELAY
# Leaves most of the inventory activity's 20 seconds to the inventory count after a stalled describe.
SCHEDULE_DESCRIBE_TIMEOUT = dt.timedelta(seconds=5)


@frozen
class AlertsPlatformInputs:
    pass


@activity.defn
async def alerts_platform_discover_demand_activity(inputs: DemandDiscoveryInputs) -> AlertDemand:
    demand = await database_sync_to_async_pool(discover_demand)(inputs.cutoff, limits_by_source=discovery_limits())
    for source, omitted in demand.omitted_by_source.items():
        if omitted:
            safe_record(increment_discovery_omitted, source.value, omitted)
    return demand


async def _tick_schedule_runs() -> TickScheduleRuns | None:
    """The tick schedule's own run counts. Temporal's namespace metrics do not say which schedule skipped."""
    try:
        async with asyncio.timeout(SCHEDULE_DESCRIBE_TIMEOUT.total_seconds()):
            info = (await a_describe_schedule(activity.client(), SCHEDULE_ID)).info
    except Exception as error:
        await LOGGER.awarning("alerts_platform_schedule_describe_failed", error=str(error))
        return None
    return TickScheduleRuns(
        started=info.num_actions,
        skipped_overlap=info.num_actions_skipped_overlap,
        missed_catchup=info.num_actions_missed_catchup_window,
    )


@activity.defn
async def alerts_platform_record_inventory_activity() -> None:
    """A failed count is logged rather than raised, so a slow count never reads as a failed workflow."""
    schedule_runs = await _tick_schedule_runs()
    # A failed push is logged and captured inside `push_registry`, never raised.
    if schedule_runs is not None:
        await asyncio.to_thread(push_tick_schedule_runs, schedule_runs)
    now = dt.datetime.now(dt.UTC)
    try:
        inventories = await database_sync_to_async_pool(count_inventory)(now)
    except Exception as error:
        await LOGGER.awarning("alerts_platform_inventory_failed", error=str(error))
        return
    await asyncio.to_thread(push_inventory, inventories)


@activity.defn
async def alerts_platform_probe_postgres_activity() -> None:
    try:
        await sync_to_async(check_postgres_connection, thread_sensitive=False)()
    except (OperationalError, InterfaceError):
        raise ApplicationError("Postgres connectivity probe failed", type=POSTGRES_PROBE_FAILURE) from None


@activity.defn
async def alerts_platform_deliver_activity() -> None:
    pass


@activity.defn
async def alerts_platform_emit_transitions_activity(request: AlertDeliveryRequest) -> None:
    """Emits nothing. Only a run that recorded TRANSITION_EVENTS_PATCH schedules it, and the flag that
    enabled the event was never on, so the run gets the result it always got."""


@activity.defn
async def alerts_platform_deliver_preview_activity(request: AlertDeliveryRequest) -> None:
    """Sends what one evaluation decided, once destinations are live for the team.

    Until then it records what it would have sent and contacts nobody, which is the same shape
    the activity has had since the PoC.

    The delivery package is synchronous: it reads the history, resolves destinations through
    the ORM and posts over a blocking client. Django refuses an ORM call from a thread with a
    running event loop, so the whole call crosses on the pool rather than one part of it.
    """
    try:
        outcome = await database_sync_to_async_pool(deliver_evaluation)(request)
    except ThreadBusy as error:
        await LOGGER.ainfo(
            "alerts_platform_delivery_thread_busy",
            source=request.source.value,
            configuration_id=request.configuration_id,
            evaluation_key=request.evaluation_key,
        )
        # Non-retryable so that the wait does not use the retries a provider failure needs, and
        # non-reportable because a held thread is expected contention. The workflow waits it out.
        raise NonReportableApplicationError(str(error), type=THREAD_BUSY, non_retryable=True) from error
    if not outcome.live:
        await LOGGER.ainfo(
            "alerts_platform_delivery_preview",
            source=request.source.value,
            configuration_id=request.configuration_id,
            evaluation_key=request.evaluation_key,
        )
        safe_record(increment_deliveries_previewed, request.source.value)
        return

    await LOGGER.ainfo(
        "alerts_platform_delivered",
        source=request.source.value,
        configuration_id=request.configuration_id,
        evaluation_key=request.evaluation_key,
        sent=outcome.sent,
        skipped_without_transport=outcome.skipped_without_transport,
        emitted_transitions=outcome.emitted_transitions,
        emitted_events=outcome.emitted_events,
    )


@workflow.defn(name="alerts-platform-deliver-preview")
class AlertsPlatformDeliverPreviewWorkflow(PostHogWorkflow):
    inputs_cls = AlertDeliveryRequest

    @workflow.run
    async def run(self, inputs: AlertDeliveryRequest) -> None:
        """Delivers each part in turn, so a split evaluation's sends to one destination never overlap.

        A part that fails does not stop the parts after it. The first failure fails the run once
        every part has had its attempts, a failed send before a failed emission.
        """
        parts = [inputs] if inputs.parts <= 1 else [replace(inputs, part=part) for part in range(inputs.parts)]
        emission_failures: list[ActivityError] = []
        if not workflow.patched(NO_TRANSITION_EVENTS_PATCH) and workflow.patched(TRANSITION_EVENTS_PATCH):
            for request in parts:
                try:
                    await self._emit(request)
                except ActivityError as error:
                    emission_failures.append(error)
        send_failures: list[ActivityError] = []
        for request in parts:
            try:
                await self._send(request)
            except ActivityError as error:
                send_failures.append(error)
        failures = [*send_failures, *emission_failures]
        if failures:
            raise failures[0]

    async def _emit(self, request: AlertDeliveryRequest) -> None:
        await workflow.execute_activity(
            alerts_platform_emit_transitions_activity,
            request,
            start_to_close_timeout=DELIVERY_START_TO_CLOSE,
            schedule_to_close_timeout=DELIVERY_SCHEDULE_TO_CLOSE,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _send(self, request: AlertDeliveryRequest) -> None:
        busy_deadline: dt.datetime | None = None
        while True:
            started_at = workflow.now()
            try:
                await workflow.execute_activity(
                    alerts_platform_deliver_preview_activity,
                    request,
                    start_to_close_timeout=DELIVERY_START_TO_CLOSE,
                    schedule_to_close_timeout=DELIVERY_SCHEDULE_TO_CLOSE,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                return
            except ActivityError as error:
                cause = unwrap_temporal_cause(error)
                if cause is None or cause.type != THREAD_BUSY:
                    raise
                if busy_deadline is None:
                    busy_deadline = workflow.now() + BUSY_WAIT_LIMIT
                elif started_at >= busy_deadline:
                    raise
            await workflow.sleep(BUSY_RETRY_DELAY)


def delivery_workflow_id(delivery: AlertDeliveryRequest) -> str:
    """The id of an evaluation's delivery. A re-run of the same occasion reuses it, so one delivery
    runs whichever caller starts it."""
    return f"alerts-deliver-preview-{delivery.configuration_id}:{delivery.evaluation_key}"


def delivery_execution_timeout(delivery: AlertDeliveryRequest) -> dt.timedelta:
    return DELIVERY_EXECUTION_TIMEOUT * max(1, delivery.parts)


async def start_deliveries(
    deliveries: Sequence[AlertDeliveryRequest],
    *,
    id_reuse_policy: WorkflowIDReusePolicy = WorkflowIDReusePolicy.ALLOW_DUPLICATE,
) -> int:
    """Starts one delivery workflow per request, from inside a source's evaluation workflow.

    Returns how many started. The id names the configuration and the evaluation key, because the
    key names a window or a slot but not the alert, so two alerts in one slot do not collide. A
    re-run of the same occasion reuses the ids, and a reused id raises, so one delivery already
    started does not stop the rest.

    A request split into parts still starts one workflow, which delivers the parts in turn, so its
    deadline is one part's times the count.
    """
    results = await asyncio.gather(
        *(
            workflow.start_child_workflow(
                AlertsPlatformDeliverPreviewWorkflow.run,
                delivery,
                id=delivery_workflow_id(delivery),
                task_queue=settings.ALERTS_PLATFORM_DELIVERY_TASK_QUEUE,
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                execution_timeout=delivery_execution_timeout(delivery),
                id_reuse_policy=id_reuse_policy,
            )
            for delivery in deliveries
        ),
        return_exceptions=True,
    )
    started = 0
    for result in results:
        if isinstance(result, WorkflowAlreadyStartedError):
            continue
        if isinstance(result, BaseException):
            raise result
        started += 1
    return started


# Holds one sweep releases. A sweep that finds more leaves the rest to the next minute's run.
MAX_HOLDS_PER_SWEEP = 200


@activity.defn
async def alerts_platform_find_expired_holds_activity() -> delivery_holds.HoldSweep:
    now = dt.datetime.now(dt.UTC)
    # A failed prune is logged, so cleanup never keeps a due hold from being sent.
    try:
        pruned = await database_sync_to_async_pool(delivery_holds.prune_holds)(now, limit=MAX_HOLDS_PER_SWEEP)
    except Exception as error:
        await LOGGER.awarning("alerts_platform_holds_prune_failed", error=str(error))
    else:
        if pruned:
            await LOGGER.ainfo("alerts_platform_holds_pruned", count=pruned)
    return await database_sync_to_async_pool(delivery_holds.holds_to_send)(now, limit=MAX_HOLDS_PER_SWEEP)


@activity.defn
async def alerts_platform_release_expired_holds_activity(sweep: delivery_holds.HoldSweep) -> list[AlertDeliveryRequest]:
    """Separate from the find, so a retry after a committed release gets the same requests back."""
    swept = await database_sync_to_async_pool(delivery_holds.send_swept)(
        sweep, dt.datetime.now(dt.UTC), max_bytes=MAX_BATCH_PAYLOAD_BYTES
    )
    # Only the holds this attempt released at their deadline, so a recovered send or a retry is not
    # counted as a source that stalled.
    for request in swept.expired:
        await LOGGER.awarning(
            "alerts_platform_hold_expired",
            source=request.source.value,
            configuration_id=request.configuration_id,
            evaluation_key=request.evaluation_key,
        )
        safe_record(increment_holds_expired, request.source.value)
    return list(swept.requests)


@activity.defn
async def alerts_platform_record_hold_deliveries_started_activity(requests: list[AlertDeliveryRequest]) -> None:
    addresses = [
        HeldDeliveryAddress(
            team_id=request.team_id, configuration_id=request.configuration_id, evaluation_key=request.evaluation_key
        )
        for request in requests
    ]
    await database_sync_to_async_pool(delivery_holds.record_delivery_started)(addresses, dt.datetime.now(dt.UTC))


@workflow.defn(name="alerts-platform-release-expired-holds")
class AlertsPlatformReleaseExpiredHoldsWorkflow(PostHogWorkflow):
    """The safety net for held deliveries: sends each one whose deadline passed with no release.

    One release of a hold wins, so a source that releases it at the same moment cannot also send it.
    A send is marked started only once its delivery started, so a run that fails between the two
    leaves it for a later run. The delivery keeps its usual id, so starting it twice starts nothing new.
    """

    inputs_cls = AlertsPlatformInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: AlertsPlatformInputs) -> int:
        sweep = await workflow.execute_activity(
            alerts_platform_find_expired_holds_activity,
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not sweep.expired and not sweep.unstarted:
            return 0
        requests = await workflow.execute_activity(
            alerts_platform_release_expired_holds_activity,
            sweep,
            start_to_close_timeout=dt.timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        # A recovered send may have delivered already and lost only its start mark. A completed
        # delivery is not run again; a failed one is.
        started = await start_deliveries(requests, id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY)
        await workflow.execute_activity(
            alerts_platform_record_hold_deliveries_started_activity,
            requests,
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return started


@workflow.defn(name="alerts-platform-deliver")
class AlertsPlatformDeliverWorkflow(PostHogWorkflow):
    inputs_cls = AlertsPlatformInputs

    @workflow.run
    async def run(self, inputs: AlertsPlatformInputs) -> None:
        await workflow.execute_activity(
            alerts_platform_deliver_activity,
            start_to_close_timeout=dt.timedelta(seconds=10),
            schedule_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@workflow.defn(name="alerts-platform-evaluate")
class AlertsPlatformEvaluateWorkflow(PostHogWorkflow):
    inputs_cls = AlertsPlatformInputs

    @workflow.run
    async def run(self, inputs: AlertsPlatformInputs) -> None:
        try:
            await workflow.execute_activity(
                alerts_platform_probe_postgres_activity,
                task_queue=settings.ALERTS_PLATFORM_EVALUATION_TASK_QUEUE,
                start_to_close_timeout=POSTGRES_PROBE_START_TO_CLOSE_TIMEOUT,
                schedule_to_close_timeout=POSTGRES_PROBE_SCHEDULE_TO_CLOSE_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except ActivityError as error:
            if isinstance(error.cause, ApplicationError) and error.cause.type == POSTGRES_PROBE_FAILURE:
                pass
            elif isinstance(error.cause, TimeoutError) and error.cause.type in (
                TimeoutType.START_TO_CLOSE,
                TimeoutType.SCHEDULE_TO_CLOSE,
            ):
                workflow.logger.warning("Postgres probe timed out; database outcome unknown; delivery is continuing")
            else:
                raise
        # Delivery must outlive the tick, so wait for start confirmation without awaiting the handle.
        await workflow.start_child_workflow(
            AlertsPlatformDeliverWorkflow.run,
            inputs,
            id=f"alerts-platform-deliver-{workflow.info().run_id}",
            task_queue=settings.ALERTS_PLATFORM_DELIVERY_TASK_QUEUE,
            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
            execution_timeout=dt.timedelta(minutes=1),
        )


@workflow.defn(name="alerts-platform-source-dispatch")
class AlertsPlatformSourceDispatchWorkflow(PostHogWorkflow):
    """One run per source per page. Receives all of the source's remaining demand, starts one
    evaluation child per batch key up to `MAX_EVALUATIONS_PER_DISPATCH`, and reports the keys it
    did not take so a later page picks them up.

    Never waits for evaluation. Children are started with ABANDON so they outlive this
    workflow and the tick that owns it.
    """

    inputs_cls = SourceDispatchInputs

    @workflow.run
    async def run(self, inputs: SourceDispatchInputs) -> SourceDispatchReport:
        taken = inputs.batch_keys[:MAX_EVALUATIONS_PER_DISPATCH]
        remaining = inputs.batch_keys[MAX_EVALUATIONS_PER_DISPATCH:]

        if workflow.patched(CONCURRENT_EVALUATION_STARTS_PATCH):
            outcomes = await asyncio.gather(*(self._start_evaluation(inputs, key) for key in taken))
        else:
            outcomes = [await self._start_evaluation(inputs, key) for key in taken]
        started_ids = [workflow_id for workflow_id in outcomes if workflow_id is not None]
        already_running = len(outcomes) - len(started_ids)

        if already_running:
            workflow.logger.info(
                "Skipped %d %s evaluations still running from an earlier tick", already_running, inputs.source.value
            )
        return SourceDispatchReport(
            source=inputs.source,
            page=inputs.page,
            dispatched=len(started_ids),
            remaining_keys=remaining,
            evaluation_workflow_ids=started_ids,
            already_running=already_running,
        )

    async def _start_evaluation(self, inputs: SourceDispatchInputs, key: AlertBatchKey) -> str | None:
        """The started evaluation's id, or None when that key's evaluation still runs from an earlier tick."""
        evaluation_workflow_id = f"alerts-eval-{inputs.source.value}-{key.team_id}-{key.slot}"
        binding = SOURCE_BINDINGS.get(inputs.source)
        try:
            if binding is None:
                # No adapter yet. The key is not passed to the noop, and the probe path stays as is.
                await workflow.start_child_workflow(
                    AlertsPlatformEvaluateWorkflow.run,
                    AlertsPlatformInputs(),
                    id=evaluation_workflow_id,
                    task_queue=settings.ALERTS_PLATFORM_EVALUATION_TASK_QUEUE,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                    execution_timeout=NOOP_EVALUATION_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            else:
                await workflow.start_child_workflow(
                    binding.workflow,
                    SourceEvaluationInputs(source=inputs.source, cutoff=inputs.cutoff, batch_key=key),
                    id=evaluation_workflow_id,
                    task_queue=binding.task_queue,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                    execution_timeout=binding.evaluation_timeout,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
        except WorkflowAlreadyStartedError:
            # Skipping is how a slow evaluation blocks its own re-dispatch. Letting the error
            # escape would fail this page, and the orchestrator awaits its pages, so the tick.
            return None
        return evaluation_workflow_id


@workflow.defn(name="alerts-platform-record-inventory")
class AlertsPlatformRecordInventoryWorkflow(PostHogWorkflow):
    inputs_cls = AlertsPlatformInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: AlertsPlatformInputs) -> None:
        await workflow.execute_activity(
            alerts_platform_record_inventory_activity,
            start_to_close_timeout=dt.timedelta(seconds=20),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


def _should_continue_as_new() -> bool:
    return workflow.info().is_continue_as_new_suggested()


def _finished_tick(result: OrchestrateResult, cutoff_iso: str) -> OrchestrateResult:
    """Records how long the tick took from its scheduled minute.

    The tick logs no other line, so this one is how an investigation reads a single tick's numbers.
    """
    duration = workflow.now() - dt.datetime.fromisoformat(cutoff_iso)
    safe_record(record_tick_end, duration=duration, deadline_reached=result.deadline_reached)
    # The log formatter drops `extra` fields, so the numbers go in the message.
    workflow.logger.info(
        "Alerts platform tick finished: scheduled_at=%s duration_ms=%d dispatched=%d remaining=%d pages=%d deadline_reached=%s",
        cutoff_iso,
        int(duration.total_seconds() * 1000),
        sum(page.dispatched for page in result.pages),
        result.remaining,
        len(result.pages),
        result.deadline_reached,
    )
    return result


@workflow.defn(name="alerts-platform-orchestrate")
class AlertsPlatformOrchestrateWorkflow(PostHogWorkflow):
    """One minute tick. Discovers demand once, then pages source dispatchers until the demand is
    exhausted or the dispatch budget is spent. Dispatchers are part of the tick: they keep the
    default TERMINATE close policy and their reports are awaited. Evaluation is never awaited.
    """

    inputs_cls = OrchestrateInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: OrchestrateInputs) -> OrchestrateResult:
        info = workflow.info()
        if inputs.cutoff is None or inputs.deadline is None or inputs.hard_deadline is None:
            cutoff = info.typed_search_attributes.get(
                SearchAttributeKey.for_datetime("TemporalScheduledStartTime"), info.workflow_start_time
            )
            now = workflow.now()
            record_schedule_to_start_latency(
                "alerts_platform_tick_start_delay_ms",
                scheduled_time=cutoff,
                started_time=info.start_time,
                description="Time from a tick's scheduled minute to its first workflow task",
            )
            hard_stop = info.execution_timeout or (TICK_DISPATCH_BUDGET + TICK_HARD_STOP_MARGIN)
            inputs = replace(
                inputs,
                cutoff=cutoff.isoformat(),
                deadline=(now + TICK_DISPATCH_BUDGET).isoformat(),
                hard_deadline=(now + hard_stop).isoformat(),
            )
        assert inputs.cutoff is not None and inputs.deadline is not None and inputs.hard_deadline is not None
        cutoff_iso = inputs.cutoff
        deadline = dt.datetime.fromisoformat(inputs.deadline)
        hard_deadline = dt.datetime.fromisoformat(inputs.hard_deadline)

        if inputs.demand is None:
            discovered = await workflow.execute_activity(
                alerts_platform_discover_demand_activity,
                DemandDiscoveryInputs(cutoff=inputs.cutoff),
                start_to_close_timeout=dt.timedelta(seconds=5),
                schedule_to_close_timeout=dt.timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            demand = discovered.batch_keys_by_source
            inputs = replace(inputs, omitted=sum(discovered.omitted_by_source.values()))
            safe_record(record_tick_keys, sum(len(keys) for keys in demand.values()) + inputs.omitted)
        else:
            demand = inputs.demand

        pages = list(inputs.pages or [])
        page = inputs.page
        while demand:
            # Check before a page starts, and never give a page more time than is left before the hard stop.
            # A tick always runs its first page: the deadline is a stop rule, not an admission rule.
            now = workflow.now()
            page_timeout = min(SOURCE_DISPATCH_TIMEOUT, hard_deadline - now - SOURCE_DISPATCH_HEADROOM)
            if (pages and now >= deadline) or page_timeout < SOURCE_DISPATCH_HEADROOM:
                workflow.logger.info("Tick dispatch budget spent with work remaining; the next tick takes it")
                remaining = (
                    sum(len(keys) for keys in demand.values())
                    + inputs.omitted
                    + sum(recorded.undispatched for recorded in pages)
                )
                return _finished_tick(
                    OrchestrateResult(pages=pages, remaining=remaining, deadline_reached=True), cutoff_iso
                )
            # One list, so the settled results below can be read back against the source that
            # produced each one.
            paged = sorted(demand.items())
            handles = [
                await workflow.start_child_workflow(
                    AlertsPlatformSourceDispatchWorkflow.run,
                    SourceDispatchInputs(
                        tick_id=info.workflow_id,
                        source=source,
                        page=page,
                        batch_keys=batch_keys,
                        cutoff=cutoff_iso,
                    ),
                    id=f"{info.workflow_id}-{source.value}-p{page}",
                    # The tick awaits these, so they run on its own fleet. An evaluation fleet with
                    # no free slots would otherwise leave the dispatcher unpicked and stall the tick.
                    task_queue=settings.ALERTS_PLATFORM_SHARED_ORCHESTRATION_TASK_QUEUE,
                    execution_timeout=page_timeout,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                for source, batch_keys in paged
            ]
            settled = await asyncio.gather(*handles, return_exceptions=True)
            reports: list[SourceDispatchReport] = []
            failed_sources = 0
            undispatched = 0
            for (dispatched_source, dispatched_keys), outcome in zip(paged, settled, strict=True):
                if isinstance(outcome, SourceDispatchReport):
                    reports.append(outcome)
                    continue
                if not isinstance(outcome, ChildWorkflowError):
                    # Only a dispatcher's own failure is a source failure. A cancellation, a
                    # determinism error or a bug in this workflow would otherwise be absorbed on
                    # every tick behind a report that says the tick completed.
                    raise outcome
                # A broken adapter must not stop the sources dispatching alongside it. Nothing
                # advanced these keys' due time, and discovery orders by it, so they win a later
                # tick rather than being lost here.
                failed_sources += 1
                undispatched += len(dispatched_keys)
                workflow.logger.warning(
                    "Dispatching %s failed; its keys stay due for a later tick: %s",
                    dispatched_source.value,
                    outcome,
                )
            demand = {report.source: report.remaining_keys for report in reports if report.remaining_keys}
            pages.append(
                TickPage(
                    page=page,
                    run_id=info.run_id,
                    dispatched=sum(report.dispatched for report in reports),
                    remaining=sum(len(report.remaining_keys) for report in reports),
                    failed_sources=failed_sources,
                    undispatched=undispatched,
                )
            )
            page += 1
            if demand and _should_continue_as_new():
                workflow.continue_as_new(replace(inputs, page=page, demand=demand, pages=pages))

        return _finished_tick(
            OrchestrateResult(
                pages=pages,
                remaining=inputs.omitted + sum(recorded.undispatched for recorded in pages),
                deadline_reached=False,
            ),
            cutoff_iso,
        )


SHARED_ORCHESTRATION_WORKFLOWS: list[type[PostHogWorkflow]] = [
    AlertsPlatformOrchestrateWorkflow,
    AlertsPlatformSourceDispatchWorkflow,
    AlertsPlatformRecordInventoryWorkflow,
]
SHARED_ORCHESTRATION_ACTIVITIES: list[Callable[..., object]] = [
    alerts_platform_discover_demand_activity,
    alerts_platform_record_inventory_activity,
]
EVALUATION_WORKFLOWS: list[type[PostHogWorkflow]] = [AlertsPlatformEvaluateWorkflow]
EVALUATION_ACTIVITIES: list[Callable[..., object]] = [
    alerts_platform_probe_postgres_activity,
    alerts_platform_record_outcomes_activity,
]
DELIVERY_WORKFLOWS: list[type[PostHogWorkflow]] = [
    AlertsPlatformDeliverWorkflow,
    AlertsPlatformDeliverPreviewWorkflow,
    AlertsPlatformReleaseExpiredHoldsWorkflow,
]
DELIVERY_ACTIVITIES: list[Callable[..., object]] = [
    alerts_platform_deliver_activity,
    alerts_platform_deliver_preview_activity,
    alerts_platform_emit_transitions_activity,
    alerts_platform_find_expired_holds_activity,
    alerts_platform_release_expired_holds_activity,
    alerts_platform_record_hold_deliveries_started_activity,
]

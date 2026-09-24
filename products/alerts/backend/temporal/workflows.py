import asyncio
import datetime as dt
from collections.abc import Callable
from dataclasses import replace

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, SearchAttributeKey
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
from posthog.temporal.common.logger import get_write_only_logger

from products.alerts.backend.temporal.metrics import increment_deliveries_previewed, safe_record
from products.alerts.backend.temporal.outcomes import alerts_platform_record_outcomes_activity
from products.alerts.backend.temporal.sources import SOURCE_EVALUATION_WORKFLOWS

LOGGER = get_write_only_logger(__name__)

with workflow.unsafe.imports_passed_through():
    from django.conf import settings
    from django.db import InterfaceError, OperationalError

    from asgiref.sync import sync_to_async

    from posthog.sync import database_sync_to_async_pool

    from products.alerts.backend.facade.contracts import (
        AlertDeliveryPreview,
        AlertDemand,
        DemandDiscoveryInputs,
        OrchestrateInputs,
        OrchestrateResult,
        SourceDispatchInputs,
        SourceDispatchReport,
        SourceEvaluationInputs,
        TickPage,
    )
    from products.alerts.backend.logic.demand import discover_demand
    from products.alerts.backend.temporal.postgres import check_postgres_connection


POSTGRES_PROBE_FAILURE = "AlertsPlatformPostgresProbeFailure"

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
# What an evaluation gets end to end: its reads, its write, and the delivery children it starts.
# It has to hold every attempt a source's activities allow, because an attempt cut off here is a
# batch that decided something and recorded nothing. Evaluations are abandoned rather than
# awaited, so this does not have to fit inside the tick. It does hold the key for its duration,
# which is what blocks a slow evaluation's own re-dispatch.
SOURCE_EVALUATION_TIMEOUT = dt.timedelta(seconds=75)


@frozen
class AlertsPlatformInputs:
    pass


@activity.defn
async def alerts_platform_discover_demand_activity(inputs: DemandDiscoveryInputs) -> AlertDemand:
    return await database_sync_to_async_pool(discover_demand)(inputs.cutoff)


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
async def alerts_platform_deliver_preview_activity(preview: AlertDeliveryPreview) -> None:
    """Records what delivery would have sent. The PoC contacts no destination."""
    await LOGGER.ainfo(
        "alerts_platform_delivery_preview",
        source=preview.source.value,
        alert_id=preview.alert_id,
        alert_name=preview.alert_name,
        evaluation_key=preview.evaluation_key,
        destinations=list(preview.destination_names),
        transitions=[
            {"grouping_key": transition.grouping_key, "notification": transition.notification}
            for transition in preview.transitions
        ],
    )
    safe_record(increment_deliveries_previewed, preview.source.value)


@workflow.defn(name="alerts-platform-deliver-preview")
class AlertsPlatformDeliverPreviewWorkflow(PostHogWorkflow):
    inputs_cls = AlertDeliveryPreview

    @workflow.run
    async def run(self, inputs: AlertDeliveryPreview) -> None:
        await workflow.execute_activity(
            alerts_platform_deliver_preview_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(seconds=10),
            schedule_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


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
                start_to_close_timeout=dt.timedelta(seconds=10),
                schedule_to_close_timeout=dt.timedelta(seconds=30),
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
        source_workflow = SOURCE_EVALUATION_WORKFLOWS.get(inputs.source)

        started_ids: list[str] = []
        already_running = 0
        for key in taken:
            evaluation_workflow_id = f"alerts-eval-{inputs.source.value}-{key.team_id}-{key.slot}"
            try:
                if source_workflow is None:
                    # No adapter yet. The key is not passed to the noop, and the probe path stays as is.
                    await workflow.start_child_workflow(
                        AlertsPlatformEvaluateWorkflow.run,
                        AlertsPlatformInputs(),
                        id=evaluation_workflow_id,
                        task_queue=settings.ALERTS_PLATFORM_EVALUATION_TASK_QUEUE,
                        parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                        execution_timeout=SOURCE_EVALUATION_TIMEOUT,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                else:
                    await workflow.start_child_workflow(
                        source_workflow,
                        SourceEvaluationInputs(source=inputs.source, cutoff=inputs.cutoff, batch_key=key),
                        id=evaluation_workflow_id,
                        task_queue=settings.ALERTS_PLATFORM_EVALUATION_TASK_QUEUE,
                        parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                        execution_timeout=SOURCE_EVALUATION_TIMEOUT,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
            except WorkflowAlreadyStartedError:
                # Skipping is how a slow evaluation blocks its own re-dispatch. Letting the error
                # escape would fail this page, and the orchestrator awaits its pages, so the tick.
                already_running += 1
                continue
            started_ids.append(evaluation_workflow_id)

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


def _should_continue_as_new() -> bool:
    return workflow.info().is_continue_as_new_suggested()


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
                return OrchestrateResult(pages=pages, remaining=remaining, deadline_reached=True)
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

        return OrchestrateResult(
            pages=pages,
            remaining=inputs.omitted + sum(recorded.undispatched for recorded in pages),
            deadline_reached=False,
        )


SHARED_ORCHESTRATION_WORKFLOWS: list[type[PostHogWorkflow]] = [
    AlertsPlatformOrchestrateWorkflow,
    AlertsPlatformSourceDispatchWorkflow,
]
SHARED_ORCHESTRATION_ACTIVITIES: list[Callable[..., object]] = [alerts_platform_discover_demand_activity]
EVALUATION_WORKFLOWS: list[type[PostHogWorkflow]] = [AlertsPlatformEvaluateWorkflow]
EVALUATION_ACTIVITIES: list[Callable[..., object]] = [
    alerts_platform_probe_postgres_activity,
    alerts_platform_record_outcomes_activity,
]
DELIVERY_WORKFLOWS: list[type[PostHogWorkflow]] = [AlertsPlatformDeliverWorkflow, AlertsPlatformDeliverPreviewWorkflow]
DELIVERY_ACTIVITIES: list[Callable[..., object]] = [
    alerts_platform_deliver_activity,
    alerts_platform_deliver_preview_activity,
]

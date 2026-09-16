import asyncio
import datetime as dt
from collections.abc import Callable
from dataclasses import replace

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, SearchAttributeKey
from temporalio.exceptions import ActivityError, ApplicationError, TimeoutError, TimeoutType

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from django.conf import settings
    from django.db import InterfaceError, OperationalError

    from asgiref.sync import sync_to_async

    from products.alerts.backend.facade.contracts import (
        AlertDemand,
        DemandDiscoveryInputs,
        OrchestrateInputs,
        OrchestrateResult,
        SourceDispatchInputs,
        SourceDispatchReport,
        TickPage,
    )
    from products.alerts.backend.logic.demand import discover_synthetic_demand
    from products.alerts.backend.temporal.postgres import check_postgres_connection


POSTGRES_PROBE_FAILURE = "AlertsProductPostgresProbeFailure"

# A tick stops starting pages once this much of its minute is spent. The schedule's 50-second
# execution timeout is the backstop, and it spans continued runs.
TICK_DISPATCH_BUDGET = dt.timedelta(seconds=45)
# Where the hard stop is assumed when the run has no execution timeout of its own.
TICK_HARD_STOP_MARGIN = dt.timedelta(seconds=5)
# A dispatcher gets this long, or the time left before the hard stop, whichever is shorter.
SOURCE_DISPATCH_TIMEOUT = dt.timedelta(seconds=30)
# Time kept between a dispatcher's timeout and the hard stop, so the child closes first.
SOURCE_DISPATCH_HEADROOM = dt.timedelta(seconds=1)


@frozen
class AlertsProductInputs:
    pass


@activity.defn
async def alerts_product_discover_demand_activity(inputs: DemandDiscoveryInputs) -> AlertDemand:
    return discover_synthetic_demand(inputs.cutoff)


@activity.defn
async def alerts_product_check_due_activity() -> None:
    try:
        await sync_to_async(check_postgres_connection, thread_sensitive=False)()
    except (OperationalError, InterfaceError):
        raise ApplicationError("Postgres connectivity probe failed", type=POSTGRES_PROBE_FAILURE) from None


@activity.defn
async def alerts_product_deliver_activity() -> None:
    pass


@workflow.defn(name="alerts-product-deliver")
class AlertsProductDeliverWorkflow(PostHogWorkflow):
    inputs_cls = AlertsProductInputs

    @workflow.run
    async def run(self, inputs: AlertsProductInputs) -> None:
        await workflow.execute_activity(
            alerts_product_deliver_activity,
            start_to_close_timeout=dt.timedelta(seconds=10),
            schedule_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@workflow.defn(name="alerts-product-check-due")
class AlertsProductCheckDueWorkflow(PostHogWorkflow):
    inputs_cls = AlertsProductInputs

    @workflow.run
    async def run(self, inputs: AlertsProductInputs) -> None:
        try:
            await workflow.execute_activity(
                alerts_product_check_due_activity,
                task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
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
            AlertsProductDeliverWorkflow.run,
            inputs,
            id=f"alerts-product-deliver-{workflow.info().run_id}",
            task_queue=settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE,
            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
            execution_timeout=dt.timedelta(minutes=1),
        )


@workflow.defn(name="alerts-product-source-dispatch")
class AlertsProductSourceDispatchWorkflow(PostHogWorkflow):
    """One run per source per page. Receives all of the source's remaining demand, starts one
    evaluation child for it, and reports what it did not take. Today it takes everything: no
    adapter has said yet how much one evaluation can hold, so nothing remains and a tick is one page.

    Never waits for evaluation. The child is started with ABANDON so it outlives this
    workflow and the tick that owns it.
    """

    inputs_cls = SourceDispatchInputs

    @workflow.run
    async def run(self, inputs: SourceDispatchInputs) -> SourceDispatchReport:
        evaluation_workflow_id: str | None = None
        if inputs.configuration_ids:
            # Members are not passed to evaluation until claims exist. The probe path stays as is.
            evaluation_workflow_id = f"{workflow.info().workflow_id}-eval"
            await workflow.start_child_workflow(
                AlertsProductCheckDueWorkflow.run,
                AlertsProductInputs(),
                id=evaluation_workflow_id,
                task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                execution_timeout=dt.timedelta(seconds=40),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        return SourceDispatchReport(
            source=inputs.source,
            page=inputs.page,
            dispatched=len(inputs.configuration_ids),
            remaining_ids=[],
            evaluation_workflow_id=evaluation_workflow_id,
        )


def _should_continue_as_new() -> bool:
    return workflow.info().is_continue_as_new_suggested()


@workflow.defn(name="alerts-product-orchestrate")
class AlertsProductOrchestrateWorkflow(PostHogWorkflow):
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
        deadline = dt.datetime.fromisoformat(inputs.deadline)
        hard_deadline = dt.datetime.fromisoformat(inputs.hard_deadline)

        if inputs.demand is None:
            discovered = await workflow.execute_activity(
                alerts_product_discover_demand_activity,
                DemandDiscoveryInputs(cutoff=inputs.cutoff),
                start_to_close_timeout=dt.timedelta(seconds=5),
                schedule_to_close_timeout=dt.timedelta(seconds=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            demand = discovered.configuration_ids_by_source
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
                remaining = sum(len(ids) for ids in demand.values()) + inputs.omitted
                return OrchestrateResult(pages=pages, remaining=remaining, deadline_reached=True)
            handles = [
                await workflow.start_child_workflow(
                    AlertsProductSourceDispatchWorkflow.run,
                    SourceDispatchInputs(
                        tick_id=info.workflow_id,
                        source=source,
                        page=page,
                        configuration_ids=configuration_ids,
                    ),
                    id=f"{info.workflow_id}-{source.value}-p{page}",
                    task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
                    execution_timeout=page_timeout,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                for source, configuration_ids in sorted(demand.items())
            ]
            reports: list[SourceDispatchReport] = await asyncio.gather(*handles)
            demand = {report.source: report.remaining_ids for report in reports if report.remaining_ids}
            pages.append(
                TickPage(
                    page=page,
                    run_id=info.run_id,
                    dispatched=sum(report.dispatched for report in reports),
                    remaining=sum(len(report.remaining_ids) for report in reports),
                )
            )
            page += 1
            if demand and _should_continue_as_new():
                workflow.continue_as_new(replace(inputs, page=page, demand=demand, pages=pages))

        return OrchestrateResult(pages=pages, remaining=inputs.omitted, deadline_reached=False)


SHARED_ORCHESTRATION_WORKFLOWS: list[type[PostHogWorkflow]] = [AlertsProductOrchestrateWorkflow]
SHARED_ORCHESTRATION_ACTIVITIES: list[Callable[..., object]] = [alerts_product_discover_demand_activity]
EVALUATION_WORKFLOWS: list[type[PostHogWorkflow]] = [AlertsProductCheckDueWorkflow, AlertsProductSourceDispatchWorkflow]
EVALUATION_ACTIVITIES: list[Callable[..., object]] = [alerts_product_check_due_activity]
DELIVERY_WORKFLOWS: list[type[PostHogWorkflow]] = [AlertsProductDeliverWorkflow]
DELIVERY_ACTIVITIES: list[Callable[..., object]] = [alerts_product_deliver_activity]

"""PR 2 rules, each asserted against a real Temporal test server:

- the real dispatcher takes everything, starts one abandoned evaluation, and reports nothing remaining
- discovery runs once per tick chain, never in a continued run
- the tick awaits dispatcher reports and never an evaluation child
- the tick exits cleanly with remaining work once its dispatch budget is spent
- a dispatcher that overruns times out before the tick's hard stop; a started evaluation survives
- a continued run carries the demand and skips discovery

The paging rules use a test dispatcher registered under the real dispatcher's name. It takes one ID
per run and reports the rest, which the real dispatcher cannot do until an adapter sets a limit.
"""

import uuid
import asyncio
import datetime as dt
from collections.abc import AsyncIterator, Iterator

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

import pytest_asyncio
from temporalio import activity, workflow
from temporalio.api.enums.v1 import EventType, ParentClosePolicy
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowFailureError
from temporalio.exceptions import ChildWorkflowError, TimeoutError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from products.alerts.backend.facade.contracts import (
    AlertDemand,
    DemandDiscoveryInputs,
    OrchestrateInputs,
    OrchestrateResult,
    SourceDispatchInputs,
    SourceDispatchReport,
    SourceKind,
)
from products.alerts.backend.facade.temporal import (
    EVALUATION_ACTIVITIES,
    EVALUATION_WORKFLOWS,
    SHARED_ORCHESTRATION_WORKFLOWS,
)
from products.alerts.backend.temporal import postgres, workflows
from products.alerts.backend.temporal.workflows import (
    AlertsProductCheckDueWorkflow,
    AlertsProductInputs,
    AlertsProductOrchestrateWorkflow,
    AlertsProductSourceDispatchWorkflow,
)

ORCHESTRATION_QUEUE = settings.ALERTS_PRODUCT_SHARED_ORCHESTRATION_TASK_QUEUE
EVALUATION_QUEUE = settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE


@workflow.defn(name="alerts-product-source-dispatch")
class PagingDispatcher:
    """Stands in for the real dispatcher: takes one ID per run, reports the rest. Same child edge."""

    @workflow.run
    async def run(self, inputs: SourceDispatchInputs) -> SourceDispatchReport:
        await workflow.execute_activity(
            "test_page_gate", inputs.configuration_ids, start_to_close_timeout=dt.timedelta(seconds=30)
        )
        evaluation_workflow_id = f"{workflow.info().workflow_id}-eval"
        await workflow.start_child_workflow(
            AlertsProductCheckDueWorkflow.run,
            AlertsProductInputs(),
            id=evaluation_workflow_id,
            task_queue=EVALUATION_QUEUE,
            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
        )
        return SourceDispatchReport(
            source=inputs.source,
            page=inputs.page,
            dispatched=1,
            remaining_ids=inputs.configuration_ids[1:],
            evaluation_workflow_id=evaluation_workflow_id,
        )


@pytest_asyncio.fixture(scope="module")
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest_asyncio.fixture(scope="module")
async def local_environment() -> AsyncIterator[WorkflowEnvironment]:
    """A real dev server. The time-skipping server does not cascade parent-close policies after a parent times out."""
    async with await WorkflowEnvironment.start_local() as env:
        yield env


@pytest.fixture(autouse=True)
def postgres_cursor() -> Iterator[MagicMock]:
    with patch.object(postgres, "execute_with_timeout") as execute:
        execute.return_value.__enter__.return_value.fetchone.return_value = (1,)
        yield execute.return_value.__enter__.return_value


def demand_activity(demand: dict[SourceKind, list[str]]):
    @activity.defn(name="alerts_product_discover_demand_activity")
    async def discover(inputs: DemandDiscoveryInputs) -> AlertDemand:
        return AlertDemand(configuration_ids_by_source=demand)

    return discover


@activity.defn(name="test_page_gate")
async def open_gate(configuration_ids: list[str]) -> None:
    pass


def workers(client: Client, discover, *, paging: bool, gate=open_gate):
    runner = UnsandboxedWorkflowRunner()
    evaluation_workflows = [AlertsProductCheckDueWorkflow, PagingDispatcher] if paging else EVALUATION_WORKFLOWS
    return (
        Worker(
            client,
            task_queue=ORCHESTRATION_QUEUE,
            workflows=SHARED_ORCHESTRATION_WORKFLOWS,
            activities=[discover],
            workflow_runner=runner,
        ),
        Worker(
            client,
            task_queue=EVALUATION_QUEUE,
            workflows=evaluation_workflows,
            activities=[*EVALUATION_ACTIVITIES, gate],
            workflow_runner=runner,
        ),
    )


def events_of(history, event_type: int) -> list:
    return [event for event in history.events if event.event_type == event_type]


async def run_tick(client: Client, tick_id: str, **kwargs) -> OrchestrateResult:
    return await client.execute_workflow(
        AlertsProductOrchestrateWorkflow.run,
        OrchestrateInputs(),
        id=tick_id,
        task_queue=ORCHESTRATION_QUEUE,
        execution_timeout=kwargs.pop("execution_timeout", dt.timedelta(seconds=50)),
    )


async def test_real_dispatcher_takes_everything_and_abandons_one_evaluation(environment: WorkflowEnvironment) -> None:
    client = environment.client
    dispatcher_id = f"dispatch-{uuid.uuid4()}"
    async with Worker(
        client,
        task_queue=EVALUATION_QUEUE,
        workflows=EVALUATION_WORKFLOWS,
        activities=EVALUATION_ACTIVITIES,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        report: SourceDispatchReport = await client.execute_workflow(
            AlertsProductSourceDispatchWorkflow.run,
            SourceDispatchInputs(tick_id="tick", source=SourceKind.LOGS, page=0, configuration_ids=["a", "b", "c"]),
            id=dispatcher_id,
            task_queue=EVALUATION_QUEUE,
            execution_timeout=dt.timedelta(seconds=30),
        )
        assert report == SourceDispatchReport(
            source=SourceKind.LOGS,
            page=0,
            dispatched=3,
            remaining_ids=[],
            evaluation_workflow_id=f"{dispatcher_id}-eval",
        )
        history = await client.get_workflow_handle(dispatcher_id).fetch_history()
        assert events_of(history, EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED) == []
        initiated = events_of(history, EventType.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED)
        assert len(initiated) == 1
        child = initiated[0].start_child_workflow_execution_initiated_event_attributes
        assert child.workflow_type.name == "alerts-product-check-due"
        assert child.parent_close_policy == ParentClosePolicy.PARENT_CLOSE_POLICY_ABANDON
        assert child.workflow_execution_timeout.ToTimedelta() == dt.timedelta(seconds=40)
        # The dispatcher completed without waiting for the evaluation; the evaluation finishes on its own.
        assert events_of(history, EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_COMPLETED) == []
        evaluation = client.get_workflow_handle(f"{dispatcher_id}-eval")
        assert await evaluation.result() is None
        assert (await evaluation.describe()).status == WorkflowExecutionStatus.COMPLETED


async def test_tick_with_real_dispatchers_is_one_page(environment: WorkflowEnvironment) -> None:
    client = environment.client
    tick_id = f"tick-{uuid.uuid4()}"
    demand = {SourceKind.LOGS: ["l1", "l2", "l3"], SourceKind.INSIGHT: ["i1"]}
    orchestration, evaluation = workers(client, demand_activity(demand), paging=False)
    async with orchestration, evaluation:
        result = await run_tick(client, tick_id)
    assert [(page.page, page.dispatched, page.remaining) for page in result.pages] == [(0, 4, 0)]
    assert result == OrchestrateResult(pages=result.pages, remaining=0, deadline_reached=False)


async def test_tick_pages_until_demand_is_exhausted(environment: WorkflowEnvironment) -> None:
    client = environment.client
    tick_id = f"tick-{uuid.uuid4()}"
    demand = {SourceKind.LOGS: ["l1", "l2", "l3"], SourceKind.INSIGHT: ["i1"]}
    orchestration, evaluation = workers(client, demand_activity(demand), paging=True)
    async with orchestration, evaluation:
        result = await run_tick(client, tick_id)
        assert [(page.page, page.dispatched, page.remaining) for page in result.pages] == [
            (0, 2, 2),
            (1, 1, 1),
            (2, 1, 0),
        ]
        assert result.remaining == 0 and not result.deadline_reached
        assert len({page.run_id for page in result.pages}) == 1

        history = await client.get_workflow_handle(tick_id).fetch_history()
        await Replayer(
            workflows=SHARED_ORCHESTRATION_WORKFLOWS, workflow_runner=UnsandboxedWorkflowRunner()
        ).replay_workflow(history)
        scheduled = events_of(history, EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED)
        assert [event.activity_task_scheduled_event_attributes.activity_type.name for event in scheduled] == [
            "alerts_product_discover_demand_activity"
        ]
        started = events_of(history, EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED)
        children = {
            event.child_workflow_execution_started_event_attributes.workflow_execution.workflow_id: (
                event.child_workflow_execution_started_event_attributes.workflow_type.name
            )
            for event in started
        }
        assert children == {
            f"{tick_id}-insight-p0": "alerts-product-source-dispatch",
            f"{tick_id}-logs-p0": "alerts-product-source-dispatch",
            f"{tick_id}-logs-p1": "alerts-product-source-dispatch",
            f"{tick_id}-logs-p2": "alerts-product-source-dispatch",
        }
        for event in events_of(history, EventType.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED):
            attributes = event.start_child_workflow_execution_initiated_event_attributes
            assert attributes.parent_close_policy == ParentClosePolicy.PARENT_CLOSE_POLICY_TERMINATE
            assert attributes.task_queue.name == EVALUATION_QUEUE
            assert attributes.workflow_execution_timeout.ToTimedelta() == dt.timedelta(seconds=30)
        # The tick awaited every dispatcher report. Evaluations are grandchildren and never awaited here.
        assert len(events_of(history, EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_COMPLETED)) == 4
        for dispatcher_id in children:
            evaluation_status = (await client.get_workflow_handle(f"{dispatcher_id}-eval").describe()).status
            assert evaluation_status == WorkflowExecutionStatus.COMPLETED


async def test_tick_exits_cleanly_when_dispatch_budget_is_spent(environment: WorkflowEnvironment) -> None:
    client = environment.client
    tick_id = f"tick-{uuid.uuid4()}"
    orchestration, evaluation = workers(client, demand_activity({SourceKind.LOGS: ["l1", "l2", "l3"]}), paging=True)
    with patch.object(workflows, "TICK_DISPATCH_BUDGET", dt.timedelta(0)):
        async with orchestration, evaluation:
            result = await run_tick(client, tick_id)
    assert result.deadline_reached
    assert [(page.page, page.dispatched, page.remaining) for page in result.pages] == [(0, 1, 2)]
    assert result.remaining == 2
    assert (await client.get_workflow_handle(tick_id).describe()).status == WorkflowExecutionStatus.COMPLETED


async def test_continued_run_carries_demand_and_skips_discovery(environment: WorkflowEnvironment) -> None:
    client = environment.client
    tick_id = f"tick-{uuid.uuid4()}"
    orchestration, evaluation = workers(client, demand_activity({SourceKind.LOGS: ["l1", "l2"]}), paging=True)
    with patch.object(workflows, "_should_continue_as_new", return_value=True):
        async with orchestration, evaluation:
            result = await run_tick(client, tick_id)
    run_ids = [page.run_id for page in result.pages]
    assert len(result.pages) == 2 and run_ids[0] != run_ids[1]
    assert result.remaining == 0

    first = await client.get_workflow_handle(tick_id, run_id=run_ids[0]).fetch_history()
    assert first.events[-1].event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CONTINUED_AS_NEW
    assert len(events_of(first, EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED)) == 1
    continued = first.events[-1].workflow_execution_continued_as_new_event_attributes
    carried = await client.data_converter.decode(continued.input.payloads, [OrchestrateInputs])
    assert carried[0].demand == {SourceKind.LOGS: ["l2"]}
    assert carried[0].page == 1 and carried[0].cutoff is not None
    assert carried[0].deadline is not None and carried[0].hard_deadline is not None

    second = await client.get_workflow_handle(tick_id, run_id=run_ids[1]).fetch_history()
    assert events_of(second, EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED) == []
    assert len(events_of(second, EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED)) == 1


async def test_overrunning_dispatcher_times_out_before_the_tick_hard_stop(
    local_environment: WorkflowEnvironment,
) -> None:
    """The tick has a 3 s execution timeout, so each page gets at most 2 s. Page 1 blocks. Its dispatcher
    times out first, the tick fails with that child error instead of being terminated mid-page, and
    the evaluation page 0 started keeps running."""
    client = local_environment.client
    tick_id = f"tick-{uuid.uuid4()}"
    page_one_started = asyncio.Event()
    release = asyncio.Event()

    @activity.defn(name="test_page_gate")
    async def block_page_one(configuration_ids: list[str]) -> None:
        if configuration_ids == ["l2"]:
            page_one_started.set()
            await release.wait()

    orchestration, evaluation = workers(
        client, demand_activity({SourceKind.LOGS: ["l1", "l2"]}), paging=True, gate=block_page_one
    )
    async with orchestration, evaluation:
        handle = await client.start_workflow(
            AlertsProductOrchestrateWorkflow.run,
            OrchestrateInputs(),
            id=tick_id,
            task_queue=ORCHESTRATION_QUEUE,
            execution_timeout=dt.timedelta(seconds=3),
        )
        await asyncio.wait_for(page_one_started.wait(), timeout=20)
        with pytest.raises(WorkflowFailureError) as failure:
            await handle.result()
        release.set()  # let the blocked activity return so the worker can shut down
        assert isinstance(failure.value.cause, ChildWorkflowError)
        assert isinstance(failure.value.cause.cause, TimeoutError)

        tick_status = (await handle.describe()).status
        statuses = {
            name: (await client.get_workflow_handle(f"{tick_id}-{name}").describe()).status
            for name in ("logs-p0", "logs-p1", "logs-p0-eval")
        }
        page_one = await client.get_workflow_handle(f"{tick_id}-logs-p1").describe()
        evaluation_history = await client.get_workflow_handle(f"{tick_id}-logs-p0-eval").fetch_history()
        delivery_id = events_of(evaluation_history, EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED)[
            0
        ].child_workflow_execution_started_event_attributes.workflow_execution.workflow_id
        delivery_status = (await client.get_workflow_handle(delivery_id).describe()).status
    assert tick_status == WorkflowExecutionStatus.FAILED  # its own child error, not the execution timeout
    assert statuses["logs-p0"] == WorkflowExecutionStatus.COMPLETED
    assert statuses["logs-p1"] == WorkflowExecutionStatus.TIMED_OUT
    assert page_one.start_time is not None and page_one.close_time is not None
    assert page_one.close_time - page_one.start_time < dt.timedelta(seconds=3)
    assert statuses["logs-p0-eval"] == WorkflowExecutionStatus.COMPLETED
    assert delivery_status == WorkflowExecutionStatus.RUNNING  # abandoned grandchild, no delivery worker here

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
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

import pytest_asyncio
from temporalio import activity, workflow
from temporalio.api.enums.v1 import EventType, ParentClosePolicy
from temporalio.api.history.v1 import HistoryEvent
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowHistory
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from products.alerts.backend.facade.contracts import (
    AlertBatchKey,
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
from products.alerts.backend.temporal.sources import SOURCE_EVALUATION_WORKFLOWS
from products.alerts.backend.temporal.workflows import (
    AlertsProductEvaluateWorkflow,
    AlertsProductInputs,
    AlertsProductOrchestrateWorkflow,
    AlertsProductSourceDispatchWorkflow,
)

_team_id = 0


def key(name: str) -> AlertBatchKey:
    """One key per scenario name, so a test reads the way it did when demand was a list of ids.
    The minute is derived from the name so keys within a scenario stay distinct."""
    minute = sum(ord(character) for character in name) % 60
    return AlertBatchKey(team_id=_team_id, slot=f"2026-09-16T10:{minute:02d}:00+00:00")


@pytest.fixture(autouse=True)
def scenario_team() -> None:
    """The evaluation id is derived from the batch key and the Temporal environment is module-scoped,
    so two tests deriving the same key address one evaluation: the second dispatch finds the first
    test's abandoned evaluation still running and counts it as already running rather than
    dispatched. A team per test keeps the derived ids apart, reruns included."""
    global _team_id
    _team_id += 1


ORCHESTRATION_QUEUE = settings.ALERTS_PRODUCT_SHARED_ORCHESTRATION_TASK_QUEUE
EVALUATION_QUEUE = settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE


@workflow.defn(name="alerts-product-source-dispatch")
class PagingDispatcher:
    """Stands in for the real dispatcher: takes one ID per run, reports the rest. Same child edge."""

    @workflow.run
    async def run(self, inputs: SourceDispatchInputs) -> SourceDispatchReport:
        await workflow.execute_activity(
            "test_page_gate", [k.slot for k in inputs.batch_keys], start_to_close_timeout=dt.timedelta(seconds=30)
        )
        evaluation_workflow_id = f"{workflow.info().workflow_id}-eval"
        await workflow.start_child_workflow(
            AlertsProductEvaluateWorkflow.run,
            AlertsProductInputs(),
            id=evaluation_workflow_id,
            task_queue=EVALUATION_QUEUE,
            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
        )
        return SourceDispatchReport(
            source=inputs.source,
            page=inputs.page,
            dispatched=1,
            remaining_keys=inputs.batch_keys[1:],
            evaluation_workflow_ids=[evaluation_workflow_id],
        )


@workflow.defn(name="alerts-product-source-dispatch")
class BrokenLogsDispatcher:
    """Registered under the real dispatcher's name. Fails for logs, dispatches for every other
    source, the way a broken source adapter would."""

    @workflow.run
    async def run(self, inputs: SourceDispatchInputs) -> SourceDispatchReport:
        if inputs.source is SourceKind.LOGS:
            raise ApplicationError("the logs adapter is broken", non_retryable=True)
        return SourceDispatchReport(
            source=inputs.source,
            page=inputs.page,
            dispatched=len(inputs.batch_keys),
            remaining_keys=[],
            evaluation_workflow_ids=[],
        )


@workflow.defn(name="test-blocking-evaluation")
class BlockingEvaluation:
    """Occupies an evaluation workflow id for as long as the test needs it."""

    @workflow.run
    async def run(self) -> None:
        # No timeout, so it registers no timer and the time-skipping server cannot skip past it.
        await workflow.wait_condition(lambda: False)


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
def no_source_bindings() -> Iterator[None]:
    """These tests cover paging and the dispatch budget, not which source evaluates for real.
    Clearing the registry keeps every source on the noop path; the binding has its own test."""
    with patch.dict(SOURCE_EVALUATION_WORKFLOWS, clear=True):
        yield


@pytest.fixture(autouse=True)
def postgres_cursor() -> Iterator[MagicMock]:
    with patch.object(postgres, "execute_with_timeout") as execute:
        execute.return_value.__enter__.return_value.fetchone.return_value = (1,)
        yield execute.return_value.__enter__.return_value


DiscoverActivity = Callable[[DemandDiscoveryInputs], Awaitable[AlertDemand]]
GateActivity = Callable[[list[str]], Awaitable[None]]


def demand_activity(
    demand: dict[SourceKind, list[AlertBatchKey]], omitted: dict[SourceKind, int] | None = None
) -> DiscoverActivity:
    @activity.defn(name="alerts_product_discover_demand_activity")
    async def discover(inputs: DemandDiscoveryInputs) -> AlertDemand:
        return AlertDemand(batch_keys_by_source=demand, omitted_by_source=omitted or {})

    return discover


@activity.defn(name="test_page_gate")
async def open_gate(slots: list[str]) -> None:
    pass


def workers(
    client: Client,
    discover: DiscoverActivity | None = None,
    *,
    dispatcher: type | None = None,
    gate: GateActivity = open_gate,
) -> tuple[Worker, Worker]:
    """The two fleets a tick uses. A test dispatcher is registered under the real dispatcher's
    name, so it takes its place on the fleet the tick dispatches to."""
    runner = UnsandboxedWorkflowRunner()
    orchestration_workflows: list[type] = (
        [AlertsProductOrchestrateWorkflow, dispatcher] if dispatcher else list(SHARED_ORCHESTRATION_WORKFLOWS)
    )
    return (
        Worker(
            client,
            task_queue=ORCHESTRATION_QUEUE,
            workflows=orchestration_workflows,
            activities=[discover, gate] if discover else [gate],
            workflow_runner=runner,
        ),
        Worker(
            client,
            task_queue=EVALUATION_QUEUE,
            workflows=[*EVALUATION_WORKFLOWS, BlockingEvaluation],
            activities=EVALUATION_ACTIVITIES,
            workflow_runner=runner,
        ),
    )


def events_of(history: WorkflowHistory, event_type: int) -> list[HistoryEvent]:
    return [event for event in history.events if event.event_type == event_type]


async def run_tick(client: Client, tick_id: str) -> OrchestrateResult:
    return await client.execute_workflow(
        AlertsProductOrchestrateWorkflow.run,
        OrchestrateInputs(),
        id=tick_id,
        task_queue=ORCHESTRATION_QUEUE,
        execution_timeout=dt.timedelta(seconds=50),
    )


async def test_real_dispatcher_takes_everything_and_abandons_one_evaluation(environment: WorkflowEnvironment) -> None:
    client = environment.client
    dispatcher_id = f"dispatch-{uuid.uuid4()}"
    orchestration_worker, evaluation_worker = workers(client)
    async with orchestration_worker, evaluation_worker:
        report: SourceDispatchReport = await client.execute_workflow(
            AlertsProductSourceDispatchWorkflow.run,
            SourceDispatchInputs(
                tick_id="tick",
                source=SourceKind.LOGS,
                page=0,
                batch_keys=[key("a"), key("b"), key("c")],
                cutoff="2026-09-16T10:00:00+00:00",
            ),
            id=dispatcher_id,
            task_queue=ORCHESTRATION_QUEUE,
            execution_timeout=dt.timedelta(seconds=30),
        )
        assert report == SourceDispatchReport(
            source=SourceKind.LOGS,
            page=0,
            dispatched=3,
            remaining_keys=[],
            evaluation_workflow_ids=[
                f"alerts-eval-logs-{key('a').team_id}-{key('a').slot}",
                f"alerts-eval-logs-{key('b').team_id}-{key('b').slot}",
                f"alerts-eval-logs-{key('c').team_id}-{key('c').slot}",
            ],
        )
        history = await client.get_workflow_handle(dispatcher_id).fetch_history()
        assert events_of(history, EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED) == []
        initiated = events_of(history, EventType.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED)
        # One evaluation per key the dispatcher took, each named by the key it holds.
        assert len(initiated) == 3
        child = initiated[0].start_child_workflow_execution_initiated_event_attributes
        assert child.workflow_type.name == "alerts-product-evaluate"
        assert child.parent_close_policy == ParentClosePolicy.PARENT_CLOSE_POLICY_ABANDON
        assert child.workflow_execution_timeout.ToTimedelta() == workflows.SOURCE_EVALUATION_TIMEOUT
        # One task per child start, plus the one that completed the run. A dispatcher that awaited an
        # evaluation would need a further task to resume on its result. Counting tasks rather than
        # forbidding a child-completion event keeps this off the race with an abandoned evaluation.
        assert len(events_of(history, EventType.EVENT_TYPE_WORKFLOW_TASK_COMPLETED)) == len(initiated) + 1
        evaluation = client.get_workflow_handle(f"alerts-eval-logs-{key('a').team_id}-{key('a').slot}")
        assert await evaluation.result() is None
        assert (await evaluation.describe()).status == WorkflowExecutionStatus.COMPLETED


async def test_a_key_whose_evaluation_still_runs_is_skipped_without_losing_the_page(
    environment: WorkflowEnvironment,
) -> None:
    client = environment.client
    held, free = key("held"), key("free")
    held_id = f"alerts-eval-logs-{held.team_id}-{held.slot}"
    orchestration_worker, evaluation_worker = workers(client)
    async with orchestration_worker, evaluation_worker:
        blocker = await client.start_workflow(BlockingEvaluation.run, id=held_id, task_queue=EVALUATION_QUEUE)
        try:
            report: SourceDispatchReport = await client.execute_workflow(
                AlertsProductSourceDispatchWorkflow.run,
                SourceDispatchInputs(
                    tick_id="tick",
                    source=SourceKind.LOGS,
                    page=0,
                    batch_keys=[held, free],
                    cutoff="2026-09-16T10:00:00+00:00",
                ),
                id=f"dispatch-{uuid.uuid4()}",
                task_queue=ORCHESTRATION_QUEUE,
                execution_timeout=dt.timedelta(seconds=30),
            )
        finally:
            await blocker.terminate()

    assert report.already_running == 1
    assert report.dispatched == 1
    assert report.evaluation_workflow_ids == [f"alerts-eval-logs-{free.team_id}-{free.slot}"]
    assert report.remaining_keys == []


async def test_tick_with_real_dispatchers_is_one_page(environment: WorkflowEnvironment) -> None:
    client = environment.client
    tick_id = f"tick-{uuid.uuid4()}"
    demand = {SourceKind.LOGS: [key("l1"), key("l2"), key("l3")], SourceKind.INSIGHT: [key("i1")]}
    orchestration, evaluation = workers(client, demand_activity(demand))
    async with orchestration, evaluation:
        result = await run_tick(client, tick_id)
    assert [(page.page, page.dispatched, page.remaining) for page in result.pages] == [(0, 4, 0)]
    assert result == OrchestrateResult(pages=result.pages, remaining=0, deadline_reached=False)


async def test_a_broken_source_dispatcher_does_not_stop_the_others(environment: WorkflowEnvironment) -> None:
    client = environment.client
    tick_id = f"tick-{uuid.uuid4()}"
    demand = {SourceKind.LOGS: [key("l1"), key("l2")], SourceKind.INSIGHT: [key("i1")]}
    orchestration, evaluation = workers(client, demand_activity(demand), dispatcher=BrokenLogsDispatcher)
    async with orchestration, evaluation:
        result = await run_tick(client, tick_id)
    # One source's dispatcher raising used to end the tick, which stopped every other source
    # evaluating for the same minute.
    assert [(page.page, page.dispatched, page.failed_sources) for page in result.pages] == [(0, 1, 1)]
    # Nothing advanced the two logs keys, so the tick reports them as still due.
    assert result.remaining == 2 and not result.deadline_reached


async def test_tick_counts_omitted_demand_as_remaining(environment: WorkflowEnvironment) -> None:
    """Discovery bounds its manifest. What it left out is still due, so the tick reports it as remaining."""
    client = environment.client
    tick_id = f"tick-{uuid.uuid4()}"
    orchestration, evaluation = workers(
        client,
        demand_activity({SourceKind.LOGS: [key("l1")]}, omitted={SourceKind.LOGS: 5}),
    )
    async with orchestration, evaluation:
        result = await run_tick(client, tick_id)
    assert [(page.page, page.dispatched, page.remaining) for page in result.pages] == [(0, 1, 0)]
    assert result.remaining == 5 and not result.deadline_reached


async def test_tick_pages_until_demand_is_exhausted(environment: WorkflowEnvironment) -> None:
    client = environment.client
    tick_id = f"tick-{uuid.uuid4()}"
    demand = {SourceKind.LOGS: [key("l1"), key("l2"), key("l3")], SourceKind.INSIGHT: [key("i1")]}
    orchestration, evaluation = workers(client, demand_activity(demand), dispatcher=PagingDispatcher)
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
            assert attributes.task_queue.name == ORCHESTRATION_QUEUE
            assert attributes.workflow_execution_timeout.ToTimedelta() == dt.timedelta(seconds=30)
        # The tick awaited every dispatcher report. Evaluations are grandchildren and never awaited here.
        assert len(events_of(history, EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_COMPLETED)) == 4
        for dispatcher_id in children:
            evaluation_status = (await client.get_workflow_handle(f"{dispatcher_id}-eval").describe()).status
            assert evaluation_status == WorkflowExecutionStatus.COMPLETED


async def test_tick_exits_cleanly_when_dispatch_budget_is_spent(environment: WorkflowEnvironment) -> None:
    client = environment.client
    tick_id = f"tick-{uuid.uuid4()}"
    orchestration, evaluation = workers(
        client, demand_activity({SourceKind.LOGS: [key("l1"), key("l2"), key("l3")]}), dispatcher=PagingDispatcher
    )
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
    orchestration, evaluation = workers(
        client, demand_activity({SourceKind.LOGS: [key("l1"), key("l2")]}), dispatcher=PagingDispatcher
    )
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
    assert carried[0].demand == {SourceKind.LOGS: [key("l2")]}
    assert carried[0].page == 1 and carried[0].cutoff is not None
    assert carried[0].deadline is not None and carried[0].hard_deadline is not None

    second = await client.get_workflow_handle(tick_id, run_id=run_ids[1]).fetch_history()
    assert events_of(second, EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED) == []
    assert len(events_of(second, EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED)) == 1


async def test_overrunning_dispatcher_times_out_before_the_tick_hard_stop(
    local_environment: WorkflowEnvironment,
) -> None:
    """The tick has a 3 s execution timeout, so each page gets at most 2 s. Page 1 blocks. Its
    dispatcher times out first rather than the tick being terminated mid-page, the tick reports that
    source as failed and still finishes, and the evaluation page 0 started keeps running."""
    client = local_environment.client
    tick_id = f"tick-{uuid.uuid4()}"
    page_one_started = asyncio.Event()
    release = asyncio.Event()

    @activity.defn(name="test_page_gate")
    async def block_page_one(slots: list[str]) -> None:
        if slots == [key("l2").slot]:
            page_one_started.set()
            await release.wait()

    orchestration, evaluation = workers(
        client,
        demand_activity({SourceKind.LOGS: [key("l1"), key("l2")]}),
        dispatcher=PagingDispatcher,
        gate=block_page_one,
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
        result = await handle.result()
        release.set()  # let the blocked activity return so the worker can shut down

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
    # The timed-out dispatcher is a failed source, not a failed tick: another source's dispatcher on
    # the same page would otherwise be terminated with it.
    assert tick_status == WorkflowExecutionStatus.COMPLETED
    assert [(page.page, page.dispatched, page.failed_sources) for page in result.pages] == [(0, 1, 0), (1, 0, 1)]
    # The key page 1 never dispatched is still due, so the tick reports it rather than dropping it.
    assert result.remaining == 1
    assert statuses["logs-p0"] == WorkflowExecutionStatus.COMPLETED
    assert statuses["logs-p1"] == WorkflowExecutionStatus.TIMED_OUT
    assert page_one.start_time is not None and page_one.close_time is not None
    assert page_one.close_time - page_one.start_time < dt.timedelta(seconds=3)
    assert statuses["logs-p0-eval"] == WorkflowExecutionStatus.COMPLETED
    assert delivery_status == WorkflowExecutionStatus.RUNNING  # abandoned grandchild, no delivery worker here

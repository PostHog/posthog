import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, Mock, patch

from structlog.testing import capture_logs
from temporalio import activity
from temporalio.api.enums.v1 import EventType
from temporalio.client import ScheduleActionStartWorkflow, ScheduleState
from temporalio.converter import DataConverter
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from products.customer_analytics.backend.logic.membership_backfill import (
    PAGE_SIZE,
    MembershipBackfillService,
    MembershipCursor,
    MembershipStep,
    MembershipSyncPage,
    MembershipTeam,
)
from products.customer_analytics.backend.temporal.membership_backfill import (
    MembershipBackfillWorkflow,
    MembershipCoordinatorInput,
    MembershipCoordinatorWorkflow,
    MembershipFailure,
    MembershipObservation,
    backfill_membership_batch_activity,
    create_membership_coordinator_schedule,
    create_membership_schedule,
    get_membership_workflow_id,
    observe_membership_backfill_activity,
    prepare_membership_backfill_activity,
    sync_membership_page_activity,
)


async def test_largest_coordinator_payload_contains_only_bounded_team_references() -> None:
    page = MembershipSyncPage(
        teams=tuple(MembershipTeam(team_id=team_id, version=2**63) for team_id in range(PAGE_SIZE)),
        next_team_id=PAGE_SIZE,
        candidates=PAGE_SIZE,
        enabled=PAGE_SIZE,
        changed=PAGE_SIZE,
    )
    payloads = await DataConverter.default.encode([page])
    assert sum(len(payload.data) for payload in payloads) < 16_384
    assert await DataConverter.default.decode(payloads, [MembershipSyncPage]) == [page]


def test_schedule_preserves_pause_and_runs_with_writes() -> None:
    state = ScheduleState(paused=True)
    schedule = create_membership_schedule(state)
    assert schedule.state.paused
    assert isinstance(schedule.action, ScheduleActionStartWorkflow)
    assert schedule.action.args == [MembershipCoordinatorInput(dry_run=False)]
    assert not create_membership_schedule(ScheduleState(paused=False)).state.paused


@pytest.mark.asyncio
async def test_schedule_update_keeps_an_operator_pause() -> None:
    client = AsyncMock()
    description = client.get_schedule_handle.return_value.describe.return_value
    description.schedule = create_membership_schedule(ScheduleState(paused=False))
    client.get_schedule_handle = Mock(return_value=client.get_schedule_handle.return_value)
    with patch("products.customer_analytics.backend.temporal.membership_backfill.a_schedule_exists", return_value=True):
        await create_membership_coordinator_schedule(client)
    updater = client.get_schedule_handle.return_value.update.call_args.kwargs["updater"]
    current = Mock(schedule=create_membership_schedule(ScheduleState(paused=True, note="Operator paused")))
    update_input = Mock(description=current)
    update = await updater(update_input)
    assert update.schedule.state.paused
    assert update.schedule.state.note == "Operator paused"


@pytest.mark.asyncio
async def test_retry_overlap_worker_restart_and_replay() -> None:
    logging.getLogger("temporalio.activity").setLevel(logging.INFO)
    logging.getLogger("temporalio.workflow").setLevel(logging.INFO)
    started = asyncio.Event()
    attempts = 0
    team = MembershipTeam(team_id=17, version=1)

    @activity.defn(name="sync_membership_page_activity")
    async def sync_page(_input: MembershipCoordinatorInput) -> MembershipSyncPage:
        return MembershipSyncPage(teams=(team,), next_team_id=None, candidates=1, enabled=1, changed=1)

    @activity.defn(name="backfill_membership_batch_activity")
    async def backfill(_input: MembershipTeam) -> MembershipStep:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ApplicationError("Retry this batch")
        if attempts == 2:
            started.set()
            return MembershipStep(status="waiting_for_dictionary")
        return MembershipStep(status="ready", rows=1)

    @activity.defn(name="fail_membership_backfill_activity")
    async def fail(_input: MembershipFailure) -> None:
        raise AssertionError("The retried batch must succeed")

    observations: list[str] = []

    @activity.defn(name="observe_membership_backfill_activity")
    async def observe(input: MembershipObservation) -> None:
        observations.append(input.event)

    queue = f"membership-test-{uuid4()}"
    async with await WorkflowEnvironment.start_time_skipping() as env:
        with env.auto_time_skipping_disabled():
            async with Worker(
                env.client,
                task_queue=queue,
                workflows=[MembershipCoordinatorWorkflow, MembershipBackfillWorkflow],
                activities=[sync_page, backfill, fail, observe],
                max_cached_workflows=0,
            ):
                await env.client.execute_workflow(
                    MembershipCoordinatorWorkflow.run,
                    MembershipCoordinatorInput(dry_run=False),
                    id=f"coordinator-{uuid4()}",
                    task_queue=queue,
                    execution_timeout=timedelta(minutes=5),
                )
                await asyncio.wait_for(started.wait(), timeout=30)
                await env.client.execute_workflow(
                    MembershipCoordinatorWorkflow.run,
                    MembershipCoordinatorInput(dry_run=False),
                    id=f"coordinator-{uuid4()}",
                    task_queue=queue,
                    execution_timeout=timedelta(minutes=5),
                )
                workflow_id = get_membership_workflow_id(team.team_id)
                handle = env.client.get_workflow_handle(workflow_id)
                handle = env.client.get_workflow_handle(workflow_id, run_id=(await handle.describe()).run_id)
                for _ in range(100):
                    history = await handle.fetch_history()
                    if any(event.event_type == EventType.EVENT_TYPE_TIMER_STARTED for event in history.events):
                        break
                    await asyncio.sleep(0.01)
                else:
                    raise AssertionError("The workflow did not start its dictionary timer")
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[MembershipCoordinatorWorkflow, MembershipBackfillWorkflow],
            activities=[sync_page, backfill, fail, observe],
        ):
            await env.sleep(timedelta(seconds=31))
            assert await asyncio.wait_for(handle.result(), timeout=30) == "ready"
        history = await handle.fetch_history()
        assert sum(event.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED for event in history.events) == 1
        assert attempts == 3
        assert observations.count("started") == 1
        assert observations[-1] == "completed"
        await Replayer(workflows=[MembershipBackfillWorkflow]).replay_workflow(history)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "has_cursor,bookkeeping_fails,observation_fails",
    [(True, False, False), (True, True, True), (False, False, False)],
)
async def test_failed_run_keeps_its_cursor_for_resume_and_can_be_cancelled(
    has_cursor: bool, bookkeeping_fails: bool, observation_fails: bool
) -> None:
    logging.getLogger("temporalio.activity").setLevel(logging.INFO)
    logging.getLogger("temporalio.workflow").setLevel(logging.INFO)
    observations: asyncio.Queue[MembershipObservation] = asyncio.Queue()
    failures: list[MembershipFailure] = []
    account_keys = ("account-a",) if has_cursor else ()
    failed = True

    @activity.defn(name="prepare_membership_backfill_activity")
    async def prepare(input: MembershipTeam) -> MembershipTeam:
        return replace(input, version=7)

    @activity.defn(name="backfill_membership_batch_activity")
    async def backfill(input: MembershipTeam) -> MembershipStep:
        assert (input.cursor.version if input.cursor else input.version) == 7
        if failed:
            raise ApplicationError("Unavailable", type="ExampleUnavailable", non_retryable=True)
        assert input.account_keys == account_keys
        return MembershipStep(status="waiting_for_dictionary", cursor=input.cursor)

    @activity.defn(name="fail_membership_backfill_activity")
    async def fail(input: MembershipFailure) -> None:
        failures.append(input)
        if bookkeeping_fails:
            raise ApplicationError("Unavailable", non_retryable=True)

    @activity.defn(name="observe_membership_backfill_activity")
    async def observe(input: MembershipObservation) -> None:
        await observations.put(input)
        if observation_fails and input.event == "failed":
            raise ApplicationError("Unavailable", non_retryable=True)

    async def wait_for_event(event: str) -> MembershipObservation:
        while True:
            observation = await asyncio.wait_for(observations.get(), timeout=30)
            if observation.event == event:
                return observation

    queue = f"membership-test-{uuid4()}"
    async with await WorkflowEnvironment.start_time_skipping() as env:
        with env.auto_time_skipping_disabled():
            async with Worker(
                env.client,
                task_queue=queue,
                workflows=[MembershipBackfillWorkflow],
                activities=[prepare, backfill, fail, observe],
            ):
                handle = await env.client.start_workflow(
                    MembershipBackfillWorkflow.run,
                    MembershipTeam(
                        team_id=17,
                        account_keys=account_keys,
                        dry_run=has_cursor,
                        cursor=MembershipCursor(
                            team_id=17,
                            version=7,
                            group_type_index=0,
                            account_keys=("account-a",),
                            dry_run=True,
                            historical_end=datetime(2026, 1, 1, tzinfo=UTC),
                            windows_completed=3,
                        )
                        if has_cursor
                        else None,
                    ),
                    id=get_membership_workflow_id(17),
                    task_queue=queue,
                    execution_timeout=timedelta(minutes=5),
                )
                assert (await wait_for_event("failed")).error_type == "ExampleUnavailable"
                assert (await handle.query(MembershipBackfillWorkflow.get_status)).status == "failed"
                assert failures[0].version == 7
                failed = False
                await handle.signal(MembershipBackfillWorkflow.resume)
                await wait_for_event("resumed")
                await wait_for_event("progress")
                await handle.signal(MembershipBackfillWorkflow.cancel)
                assert await asyncio.wait_for(handle.result(), timeout=30) == "cancelled"
                observation = await wait_for_event("cancelled")
                assert observation.input.account_keys == account_keys
                if has_cursor:
                    assert observation.input.cursor is not None
                    assert observation.input.cursor.windows_completed == 3
                    assert observation.input.cursor.historical_end == datetime(2026, 1, 1, tzinfo=UTC)
                else:
                    assert observation.input.version == 7
        await Replayer(workflows=[MembershipBackfillWorkflow]).replay_workflow(await handle.fetch_history())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["batch", "sync", "prepare"])
async def test_activity_cancellation_stops_the_database_thread(operation: str) -> None:
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    checked = asyncio.Event()
    release = Event()
    stopped: list[bool] = []

    def wait_for_cancellation(should_stop: Callable[[], bool]) -> None:
        loop.call_soon_threadsafe(started.set)
        if not release.wait(timeout=10):
            raise RuntimeError("Database thread did not finish")
        stopped.append(should_stop())
        loop.call_soon_threadsafe(checked.set)

    def process_batch(_input: MembershipTeam, *, deadline: float, should_stop: Callable[[], bool]) -> MembershipStep:
        wait_for_cancellation(should_stop)
        return MembershipStep(status="backfilling")

    def sync_page(service: MembershipBackfillService, _after: int, *, dry_run: bool) -> MembershipSyncPage:
        assert service.should_stop is not None and service.deadline is not None
        wait_for_cancellation(service.should_stop)
        return MembershipSyncPage(teams=(), next_team_id=None, candidates=0, enabled=0, changed=0)

    def prepare(service: MembershipBackfillService, input: MembershipTeam) -> MembershipTeam:
        assert service.should_stop is not None and service.deadline is not None
        wait_for_cancellation(service.should_stop)
        return input

    env = ActivityEnvironment()

    async def run_activity() -> None:
        if operation == "batch":
            await env.run(backfill_membership_batch_activity, MembershipTeam(team_id=17))
        elif operation == "sync":
            await env.run(sync_membership_page_activity, MembershipCoordinatorInput())
        else:
            await env.run(prepare_membership_backfill_activity, MembershipTeam(team_id=17))

    with (
        patch.object(MembershipBackfillService, "process_activity_batch", side_effect=process_batch),
        patch.object(MembershipBackfillService, "sync_page", autospec=True, side_effect=sync_page),
        patch.object(MembershipBackfillService, "prepare_backfill", autospec=True, side_effect=prepare),
    ):
        task = asyncio.create_task(run_activity())
        try:
            await asyncio.wait_for(started.wait(), timeout=10)
            env.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
        await asyncio.wait_for(checked.wait(), timeout=10)
    assert stopped == [True]


@pytest.mark.asyncio
async def test_monitoring_logs_use_run_counters_without_account_keys() -> None:
    cursor = MembershipCursor(
        team_id=17,
        version=1,
        group_type_index=0,
        accounts_completed=2,
        windows_completed=3,
        rows_written=7,
        rows_found=9,
    )
    observation = MembershipObservation(
        input=MembershipTeam(team_id=17, account_keys=("example-account",), cursor=cursor),
        run_id="example-run",
        event="progress",
        status="backfilling",
    )
    with capture_logs() as logs:
        await ActivityEnvironment().run(observe_membership_backfill_activity, observation)
    assert logs[0]["event"] == "customer_analytics.membership_backfill"
    assert logs[0]["backfill_run_id"] == "example-run"
    assert logs[0]["account_scope"] == "selected"
    assert logs[0]["accounts_completed"] == 2
    assert logs[0]["windows_completed"] == 3
    assert logs[0]["rows_written"] == 7
    assert "example-account" not in str(logs)

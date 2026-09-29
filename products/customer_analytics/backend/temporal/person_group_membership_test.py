import asyncio
import logging
from dataclasses import fields
from datetime import timedelta
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio import activity
from temporalio.client import ScheduleActionStartWorkflow, ScheduleOverlapPolicy, WorkflowFailureError
from temporalio.converter import DataConverter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.customer_analytics.backend.logic.person_group_membership import MembershipBackfill, MembershipStep
from products.customer_analytics.backend.temporal.person_group_membership import (
    MembershipCoordinator,
    PersonGroupMembershipBackfillWorkflow,
    PersonGroupMembershipCoordinatorWorkflow,
    build_membership_coordinator_schedule,
    create_person_group_membership_coordinator_schedule,
    membership_backfill_workflow_id,
    start_membership_backfill,
)


@pytest.mark.asyncio
async def test_schedule_is_paused_and_preserves_operator_opt_in() -> None:
    client = MagicMock()
    with (
        patch(
            "products.customer_analytics.backend.temporal.person_group_membership.a_schedule_exists",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "products.customer_analytics.backend.temporal.person_group_membership.a_create_schedule", new=AsyncMock()
        ) as create,
    ):
        await create_person_group_membership_coordinator_schedule(client)
    schedule = create.await_args.args[2]
    assert schedule.state.paused
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert isinstance(schedule.action, ScheduleActionStartWorkflow)
    assert schedule.action.args == [MembershipCoordinator()]
    assert create.await_args.kwargs["trigger_immediately"] is False

    schedule.state.paused = False
    schedule.action.args = [MembershipCoordinator(dry_run=False)]
    client.get_schedule_handle.return_value.describe = AsyncMock(return_value=MagicMock(schedule=schedule))
    with (
        patch(
            "products.customer_analytics.backend.temporal.person_group_membership.a_schedule_exists",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "products.customer_analytics.backend.temporal.person_group_membership.a_update_schedule", new=AsyncMock()
        ) as update,
    ):
        await create_person_group_membership_coordinator_schedule(client)
    updated = update.await_args.args[2]
    assert not updated.state.paused
    assert updated.action.args == [MembershipCoordinator(dry_run=False)]


@pytest.mark.asyncio
async def test_payloads_do_not_carry_rows_or_grow_with_event_volume() -> None:
    converter = DataConverter.default
    inputs = [MembershipBackfill(team_id=1, config_version=9, dry_run=False), MembershipCoordinator(after_team_id=100)]
    for input in inputs:
        payloads = await converter.encode([input])
        assert len(payloads[0].data) < 256
        assert all(field.type in {int, bool} for field in fields(input))
        assert await converter.decode(payloads, [type(input)]) == [input]
    schedule = build_membership_coordinator_schedule(MagicMock())
    assert schedule.action.task_queue


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_permanently", [False, True])
async def test_backfill_retries_waits_for_lag_and_marks_exhausted_failures(fail_permanently: bool, caplog) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    attempts = 0
    failed = []
    times = []

    @activity.defn(name="advance_membership_backfill_activity")
    async def advance(input: MembershipBackfill) -> MembershipStep:
        nonlocal attempts
        attempts += 1
        times.append(activity.info().scheduled_time)
        if fail_permanently or attempts == 1:
            raise RuntimeError("transient ClickHouse failure")
        if attempts == 2:
            return MembershipStep(status="waiting", wait_until=activity.info().scheduled_time + timedelta(seconds=120))
        return MembershipStep(status="done")

    @activity.defn(name="fail_membership_backfill_activity")
    async def fail(input: MembershipBackfill) -> None:
        failed.append(input)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="membership-test",
            workflows=[PersonGroupMembershipBackfillWorkflow],
            activities=[advance, fail],
        ):
            input = MembershipBackfill(team_id=1, config_version=2, dry_run=False)
            handle = await env.client.start_workflow(
                PersonGroupMembershipBackfillWorkflow.run,
                input,
                id=str(uuid4()),
                task_queue="membership-test",
                execution_timeout=timedelta(minutes=10),
            )
            if fail_permanently:
                with pytest.raises(WorkflowFailureError):
                    await handle.result()
                assert failed == [input]
            else:
                await handle.result()
                assert not failed
                assert times[-1] - times[-2] >= timedelta(seconds=120)
            assert attempts == 3


@pytest.mark.asyncio
async def test_coordinator_continues_with_cursor_only(caplog) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    cursors = []

    @activity.defn(name="sync_membership_page_activity")
    async def sync(input: MembershipCoordinator) -> int | None:
        cursors.append(input.after_team_id)
        assert not input.dry_run
        return input.after_team_id + 100 if input.after_team_id < 200 else None

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="membership-test",
            workflows=[PersonGroupMembershipCoordinatorWorkflow],
            activities=[sync],
        ):
            await env.client.execute_workflow(
                PersonGroupMembershipCoordinatorWorkflow.run,
                MembershipCoordinator(dry_run=False),
                id=str(uuid4()),
                task_queue="membership-test",
                execution_timeout=timedelta(minutes=10),
            )
    assert cursors == [0, 100, 200]


@pytest.mark.asyncio
async def test_one_backfill_per_team_and_index_change_can_start_after_completion(settings, caplog) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    settings.VIDEO_EXPORT_TASK_QUEUE = "membership-test"
    started = asyncio.Event()
    release = asyncio.Event()
    versions = []

    @activity.defn(name="advance_membership_backfill_activity")
    async def advance(input: MembershipBackfill) -> MembershipStep:
        versions.append(input.config_version)
        started.set()
        await release.wait()
        return MembershipStep(status="done")

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="membership-test",
            workflows=[PersonGroupMembershipBackfillWorkflow],
            activities=[advance],
        ):
            first = MembershipBackfill(team_id=1, config_version=1, dry_run=False)
            assert await start_membership_backfill(env.client, first)
            await asyncio.wait_for(started.wait(), timeout=30)
            second = MembershipBackfill(team_id=1, config_version=2, dry_run=False)
            assert not await start_membership_backfill(env.client, second)
            release.set()
            await env.client.get_workflow_handle(membership_backfill_workflow_id(1)).result()
            assert await start_membership_backfill(env.client, second)
            await env.client.get_workflow_handle(membership_backfill_workflow_id(1)).result()
    assert versions == [1, 2]

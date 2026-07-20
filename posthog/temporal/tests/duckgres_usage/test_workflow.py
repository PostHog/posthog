"""Workflow orchestration test: the workflow runs the ack activity iff the poll
returned an `ack_watermark`, and hands it exactly that value.

Uses a Temporal `WorkflowEnvironment` with mock activities so we exercise the
real branch logic in `PollDuckgresUsageWorkflow.run` without touching duckgres
or the DB.
"""

import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.duckgres_usage.types import (
    PollDuckgresUsageInputs,
    PollDuckgresUsageResult,
    SetDuckgresDefaultTeamInputs,
)
from posthog.temporal.duckgres_usage.workflow import PollDuckgresUsageWorkflow, UpdateDuckgresDefaultTeamWorkflow

ACK_WATERMARK = "2026-07-06T23:59:59+00:00"
ORG_A = "018f0000-0000-0000-0000-00000000000a"


async def _run_workflow(poll_result: PollDuckgresUsageResult) -> list[str]:
    """Run the workflow with a poll that returns `poll_result`; return the list
    of watermarks the ack activity was called with."""
    acked_with: list[str] = []

    @activity.defn(name="poll-duckgres-usage")
    async def poll_mock(inputs: PollDuckgresUsageInputs) -> PollDuckgresUsageResult:
        return poll_result

    @activity.defn(name="ack-duckgres-usage")
    async def ack_mock(ack_watermark: str) -> None:
        acked_with.append(ack_watermark)

    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        async with Worker(
            env.client,
            task_queue=(tq := str(uuid.uuid4())),
            workflows=[PollDuckgresUsageWorkflow],
            activities=[poll_mock, ack_mock],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                PollDuckgresUsageWorkflow.run,
                PollDuckgresUsageInputs(),
                id=str(uuid.uuid4()),
                task_queue=tq,
            )
    return acked_with


@pytest.mark.asyncio
async def test_workflow_acks_when_poll_returns_a_watermark() -> None:
    acked_with = await _run_workflow(PollDuckgresUsageResult(rows_written=2, ack_watermark=ACK_WATERMARK))
    assert acked_with == [ACK_WATERMARK]


@pytest.mark.asyncio
async def test_workflow_does_not_ack_when_poll_withholds() -> None:
    # Hole / parse failure / nothing-closed all surface as ack_watermark=None.
    acked_with = await _run_workflow(PollDuckgresUsageResult(rows_written=1, ack_watermark=None, watermark_hole=True))
    assert acked_with == []


async def _run_workflow_capturing_repoints(poll_result: PollDuckgresUsageResult) -> list[tuple[str, int]]:
    """Run the poll workflow with a mock poll returning `poll_result`; return the
    (org_id, team_id) pairs the repoint activity was invoked with. The repoint
    children are ABANDON (they outlive the parent), so we await each by its
    deterministic id after the parent completes."""
    repointed: list[tuple[str, int]] = []

    @activity.defn(name="poll-duckgres-usage")
    async def poll_mock(inputs: PollDuckgresUsageInputs) -> PollDuckgresUsageResult:
        return poll_result

    @activity.defn(name="ack-duckgres-usage")
    async def ack_mock(ack_watermark: str) -> None:
        pass

    @activity.defn(name="set-duckgres-default-team")
    async def set_team_mock(inputs: SetDuckgresDefaultTeamInputs) -> None:
        repointed.append((inputs.org_id, inputs.team_id))

    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        async with Worker(
            env.client,
            task_queue=(tq := str(uuid.uuid4())),
            workflows=[PollDuckgresUsageWorkflow, UpdateDuckgresDefaultTeamWorkflow],
            activities=[poll_mock, ack_mock, set_team_mock],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                PollDuckgresUsageWorkflow.run,
                PollDuckgresUsageInputs(),
                id=str(uuid.uuid4()),
                task_queue=tq,
            )
            for org_id in poll_result.default_team_repoints:
                handle = env.client.get_workflow_handle(UpdateDuckgresDefaultTeamWorkflow.workflow_id_for(org_id))
                await handle.result()
    return repointed


@pytest.mark.asyncio
async def test_workflow_repoints_each_deleted_default_team() -> None:
    repointed = await _run_workflow_capturing_repoints(
        PollDuckgresUsageResult(rows_written=3, default_team_repoints={ORG_A: 7})
    )
    assert repointed == [(ORG_A, 7)]


@pytest.mark.asyncio
async def test_workflow_starts_no_repoint_when_none() -> None:
    repointed = await _run_workflow_capturing_repoints(
        PollDuckgresUsageResult(rows_written=3, default_team_repoints={})
    )
    assert repointed == []

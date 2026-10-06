import uuid
import asyncio
import dataclasses
from typing import Any

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.cdp_dlq_replay.workflow import (
    LIST_PARTITIONS_ACTIVITY,
    REPLAY_PARTITION_ACTIVITY,
    CdpDlqReplayInputs,
    CdpDlqReplayWorkflow,
    replay_workflow_id,
)

INPUTS = CdpDlqReplayInputs(
    start_timestamp="2026-10-01T00:00:00+00:00",
    end_timestamp="2026-10-02T00:00:00+00:00",
    team_id=2,
    source_ids=["fn-a"],
    skip_unreplayable=False,
)


def _result(partition: int, **overrides: Any) -> dict[str, Any]:
    return {
        "partition": partition,
        "next_offset": 10,
        "end_offset": 10,
        "records_read": 10,
        "records_in_scope": 4,
        "records_out_of_scope": 6,
        "records_unreadable": 0,
        "records_skipped": 0,
        "invocations_queued": 4,
        "skipped": [],
        "blocked": None,
        **overrides,
    }


async def _run(inputs: CdpDlqReplayInputs, replay: Any, drive: Any = None) -> Any:
    @activity.defn(name=LIST_PARTITIONS_ACTIVITY)
    async def list_partitions(_input: dict[str, Any]) -> dict[str, Any]:
        return {"topic": "cdp_events_dlq", "partitions": [0, 1]}

    @activity.defn(name=REPLAY_PARTITION_ACTIVITY)
    async def replay_partition(input: dict[str, Any]) -> dict[str, Any]:
        return replay(input)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[CdpDlqReplayWorkflow],
            activities=[list_partitions, replay_partition],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                CdpDlqReplayWorkflow.run,
                dataclasses.replace(inputs, task_queue=task_queue),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
            if drive:
                await drive(handle)
            return await handle.result()


async def _until_blocked(handle: WorkflowHandle) -> None:
    for _ in range(200):
        if any(p.status == "blocked" for p in await handle.query(CdpDlqReplayWorkflow.status)):
            return
        await asyncio.sleep(0.05)
    raise AssertionError("no partition blocked")


@pytest.mark.asyncio
async def test_replays_every_partition_with_the_window_and_scope_it_was_given():
    calls: list[dict[str, Any]] = []

    def replay(input: dict[str, Any]) -> dict[str, Any]:
        calls.append(input)
        return _result(input["partition"])

    result = await _run(INPUTS, replay)

    assert sorted(call["partition"] for call in calls) == [0, 1]
    for call in calls:
        assert call["topic"] == "cdp_events_dlq"
        assert call["start_timestamp_ms"] == 1790812800000
        assert call["end_timestamp_ms"] == 1790899200000
        assert call["team_id"] == 2
        assert call["source_ids"] == ["fn-a"]
        assert call["from_offset"] is None
    assert result.records_read == 20
    assert result.invocations_queued == 8
    assert all(p.status == "done" for p in result.partitions)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision,resume_from,skipped",
    [
        ("retry", 3, 0),
        ("skip", 4, 1),
    ],
)
async def test_a_blocked_partition_waits_and_resumes_where_the_decision_says(decision, resume_from, skipped):
    calls: list[dict[str, Any]] = []

    def replay(input: dict[str, Any]) -> dict[str, Any]:
        calls.append(input)
        if input["partition"] == 0 and input["from_offset"] is None:
            return _result(0, next_offset=3, blocked={"offset": 3, "error": "still fails to build"})
        return _result(input["partition"])

    async def drive(handle: WorkflowHandle) -> None:
        await _until_blocked(handle)
        await handle.signal(decision, 0)

    result = await _run(INPUTS, replay, drive)

    resumed = [call for call in calls if call["partition"] == 0 and call["from_offset"] is not None]
    assert [call["from_offset"] for call in resumed] == [resume_from]
    assert resumed[0]["end_offset"] == 10
    partition = next(p for p in result.partitions if p.partition == 0)
    assert partition.status == "done"
    assert partition.records_skipped == skipped
    assert result.records_skipped == skipped


@pytest.mark.parametrize(
    "change,same_id",
    [
        ({}, True),
        ({"source_ids": ["fn-a"], "batch_size": 50}, True),
        ({"dry_run": True}, False),
        ({"team_id": 3}, False),
        ({"source_ids": ["fn-b"]}, False),
        ({"end_timestamp": "2026-10-03T00:00:00+00:00"}, False),
    ],
)
def test_the_workflow_id_names_the_window_scope_and_mode(change, same_id):
    assert (replay_workflow_id(INPUTS) == replay_workflow_id(dataclasses.replace(INPUTS, **change))) is same_id

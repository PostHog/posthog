import uuid
from datetime import UTC, datetime, timedelta

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.dlq_replay.activities import (
    GetTopicPartitionsInputs,
    ReplayPartitionInputs,
    ReplayPartitionResult,
)
from posthog.temporal.dlq_replay.workflow import DLQReplayWorkflow, DLQReplayWorkflowInputs


@pytest.fixture
def activity_call_tracker():
    """Track activity calls for testing."""
    return {
        "get_partitions_calls": [],
        "replay_partition_calls": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "partition_count,expected_replay_calls",
    [
        pytest.param(1, 1, id="single_partition"),
        pytest.param(3, 3, id="multiple_partitions"),
        pytest.param(10, 10, id="many_partitions"),
    ],
)
async def test_dlq_replay_workflow_processes_all_partitions(
    activity_call_tracker, partition_count, expected_replay_calls
):
    """Verify the workflow discovers partitions and replays each one."""
    get_partitions_calls = activity_call_tracker["get_partitions_calls"]
    replay_partition_calls = activity_call_tracker["replay_partition_calls"]

    @activity.defn(name="get_topic_partitions")
    async def mock_get_topic_partitions(inputs: GetTopicPartitionsInputs) -> list[int]:
        get_partitions_calls.append(inputs)
        return list(range(partition_count))

    @activity.defn(name="replay_partition")
    async def mock_replay_partition(inputs: ReplayPartitionInputs) -> ReplayPartitionResult:
        replay_partition_calls.append(inputs)
        return ReplayPartitionResult(
            partition=inputs.partition,
            messages_replayed=100,
        )

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DLQReplayWorkflow],
            activities=[mock_get_topic_partitions, mock_replay_partition],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            start_time = datetime.now(UTC) - timedelta(hours=1)
            end_time = datetime.now(UTC)

            result = await env.client.execute_workflow(
                DLQReplayWorkflow.run,
                DLQReplayWorkflowInputs(
                    source_topic="events_dlq",
                    target_topic="events",
                    start_timestamp=start_time.isoformat(),
                    end_timestamp=end_time.isoformat(),
                    batch_size=500,
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert len(get_partitions_calls) == 1
    assert get_partitions_calls[0].topic == "events_dlq"

    assert len(replay_partition_calls) == expected_replay_calls
    assert result.total_messages_replayed == 100 * expected_replay_calls
    assert len(result.partition_results) == expected_replay_calls

    for partition in range(partition_count):
        assert partition in result.partition_results
        assert result.partition_results[partition] == 100


@pytest.mark.asyncio
async def test_dlq_replay_workflow_passes_correct_inputs(activity_call_tracker):
    """Verify the workflow passes the correct inputs to activities."""
    replay_partition_calls = activity_call_tracker["replay_partition_calls"]

    @activity.defn(name="get_topic_partitions")
    async def mock_get_topic_partitions(inputs: GetTopicPartitionsInputs) -> list[int]:
        return [0]

    @activity.defn(name="replay_partition")
    async def mock_replay_partition(inputs: ReplayPartitionInputs) -> ReplayPartitionResult:
        replay_partition_calls.append(inputs)
        return ReplayPartitionResult(partition=inputs.partition, messages_replayed=50)

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DLQReplayWorkflow],
            activities=[mock_get_topic_partitions, mock_replay_partition],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            start_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
            end_time = datetime(2024, 1, 15, 11, 0, 0, tzinfo=UTC)

            await env.client.execute_workflow(
                DLQReplayWorkflow.run,
                DLQReplayWorkflowInputs(
                    source_topic="my_dlq_topic",
                    target_topic="my_target_topic",
                    start_timestamp=start_time.isoformat(),
                    end_timestamp=end_time.isoformat(),
                    batch_size=250,
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert len(replay_partition_calls) == 1
    activity_inputs = replay_partition_calls[0]
    assert activity_inputs.source_topic == "my_dlq_topic"
    assert activity_inputs.target_topic == "my_target_topic"
    assert activity_inputs.partition == 0
    assert activity_inputs.start_timestamp_ms == int(start_time.timestamp() * 1000)
    assert activity_inputs.end_timestamp_ms == int(end_time.timestamp() * 1000)
    assert activity_inputs.batch_size == 250


@pytest.mark.asyncio
async def test_dlq_replay_workflow_defaults_end_timestamp_to_now(activity_call_tracker):
    """Verify the workflow defaults end_timestamp to workflow start time when not provided."""
    replay_partition_calls = activity_call_tracker["replay_partition_calls"]

    @activity.defn(name="get_topic_partitions")
    async def mock_get_topic_partitions(inputs: GetTopicPartitionsInputs) -> list[int]:
        return [0]

    @activity.defn(name="replay_partition")
    async def mock_replay_partition(inputs: ReplayPartitionInputs) -> ReplayPartitionResult:
        replay_partition_calls.append(inputs)
        return ReplayPartitionResult(partition=inputs.partition, messages_replayed=200)

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DLQReplayWorkflow],
            activities=[mock_get_topic_partitions, mock_replay_partition],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            start_time = datetime.now(UTC) - timedelta(hours=2)

            result = await env.client.execute_workflow(
                DLQReplayWorkflow.run,
                DLQReplayWorkflowInputs(
                    source_topic="events_dlq",
                    target_topic="events",
                    start_timestamp=start_time.isoformat(),
                    end_timestamp=None,
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert len(replay_partition_calls) == 1
    # end_timestamp_ms should be set (not None) since workflow defaults it
    assert replay_partition_calls[0].end_timestamp_ms is not None
    assert replay_partition_calls[0].end_timestamp_ms > replay_partition_calls[0].start_timestamp_ms
    assert result.total_messages_replayed == 200


@pytest.mark.asyncio
async def test_dlq_replay_workflow_handles_empty_topic():
    """Verify the workflow handles topics with no partitions gracefully."""

    @activity.defn(name="get_topic_partitions")
    async def mock_get_topic_partitions(inputs: GetTopicPartitionsInputs) -> list[int]:
        return []

    @activity.defn(name="replay_partition")
    async def mock_replay_partition(inputs: ReplayPartitionInputs) -> ReplayPartitionResult:
        raise AssertionError("Should not be called for empty topic")

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DLQReplayWorkflow],
            activities=[mock_get_topic_partitions, mock_replay_partition],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            start_time = datetime.now(UTC) - timedelta(hours=1)

            result = await env.client.execute_workflow(
                DLQReplayWorkflow.run,
                DLQReplayWorkflowInputs(
                    source_topic="nonexistent_topic",
                    target_topic="events",
                    start_timestamp=start_time.isoformat(),
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert result.total_messages_replayed == 0
    assert result.partition_results == {}


@pytest.mark.asyncio
async def test_dlq_replay_workflow_aggregates_partition_results(activity_call_tracker):
    """Verify the workflow correctly aggregates results from multiple partitions."""
    partition_message_counts = {0: 100, 1: 200, 2: 50}

    @activity.defn(name="get_topic_partitions")
    async def mock_get_topic_partitions(inputs: GetTopicPartitionsInputs) -> list[int]:
        return list(partition_message_counts.keys())

    @activity.defn(name="replay_partition")
    async def mock_replay_partition(inputs: ReplayPartitionInputs) -> ReplayPartitionResult:
        messages = partition_message_counts[inputs.partition]
        return ReplayPartitionResult(partition=inputs.partition, messages_replayed=messages)

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[DLQReplayWorkflow],
            activities=[mock_get_topic_partitions, mock_replay_partition],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            start_time = datetime.now(UTC) - timedelta(hours=1)

            result = await env.client.execute_workflow(
                DLQReplayWorkflow.run,
                DLQReplayWorkflowInputs(
                    source_topic="events_dlq",
                    target_topic="events",
                    start_timestamp=start_time.isoformat(),
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert result.total_messages_replayed == 350
    assert result.partition_results == {0: 100, 1: 200, 2: 50}

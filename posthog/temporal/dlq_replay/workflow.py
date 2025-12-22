import json
import asyncio
import datetime as dt
import dataclasses

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.dlq_replay.activities import (
        GetTopicPartitionsInputs,
        ReplayPartitionInputs,
        ReplayPartitionResult,
        get_topic_partitions,
        replay_partition,
    )


@dataclasses.dataclass
class DLQReplayWorkflowInputs:
    """Inputs for the DLQ replay workflow.

    Attributes:
        source_topic: The DLQ topic to read messages from.
        target_topic: The topic to replay messages to.
        start_timestamp: ISO format datetime string for the start of the replay window.
        end_timestamp: ISO format datetime string for the end of the replay window.
            If None, defaults to current UTC time when the workflow starts.
        batch_size: Number of messages to process in each batch.
    """

    source_topic: str
    target_topic: str
    start_timestamp: str
    end_timestamp: str | None = None
    batch_size: int = 1000


@dataclasses.dataclass
class DLQReplayWorkflowResult:
    """Result of the DLQ replay workflow.

    Attributes:
        total_messages_replayed: Total number of messages replayed across all partitions.
        partition_results: Messages replayed per partition.
    """

    total_messages_replayed: int
    partition_results: dict[int, int]


@workflow.defn(name="dlq-replay")
class DLQReplayWorkflow(PostHogWorkflow):
    """Workflow to replay messages from a Kafka DLQ topic to a target topic.

    This workflow:
    1. Discovers all partitions of the source topic
    2. Spawns parallel activities to replay each partition
    3. Aggregates results from all partitions
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> DLQReplayWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return DLQReplayWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: DLQReplayWorkflowInputs) -> DLQReplayWorkflowResult:
        """Execute the DLQ replay workflow."""
        # Convert timestamps to milliseconds
        start_dt = dt.datetime.fromisoformat(inputs.start_timestamp)
        start_timestamp_ms = int(start_dt.timestamp() * 1000)

        # Default end_timestamp to current UTC time if not provided
        if inputs.end_timestamp:
            end_dt = dt.datetime.fromisoformat(inputs.end_timestamp)
            end_timestamp_ms = int(end_dt.timestamp() * 1000)
        else:
            end_timestamp_ms = int(workflow.now().timestamp() * 1000)

        # Step 1: Get all partitions for the source topic
        partitions: list[int] = await workflow.execute_activity(
            get_topic_partitions,
            GetTopicPartitionsInputs(topic=inputs.source_topic),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=5),
                maximum_interval=dt.timedelta(seconds=30),
                maximum_attempts=3,
            ),
        )

        if not partitions:
            return DLQReplayWorkflowResult(total_messages_replayed=0, partition_results={})

        # Step 2: Replay each partition in parallel
        partition_tasks = []
        for partition in partitions:
            task = workflow.execute_activity(
                replay_partition,
                ReplayPartitionInputs(
                    source_topic=inputs.source_topic,
                    target_topic=inputs.target_topic,
                    partition=partition,
                    start_timestamp_ms=start_timestamp_ms,
                    end_timestamp_ms=end_timestamp_ms,
                    batch_size=inputs.batch_size,
                ),
                start_to_close_timeout=dt.timedelta(hours=4),
                heartbeat_timeout=dt.timedelta(minutes=2),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=5),
                    maximum_attempts=3,
                ),
            )
            partition_tasks.append(task)

        # Wait for all partition replays to complete
        results: list[ReplayPartitionResult] = await asyncio.gather(*partition_tasks)

        # Step 3: Aggregate results
        total_messages_replayed = 0
        partition_results: dict[int, int] = {}

        for result in results:
            partition_results[result.partition] = result.messages_replayed
            total_messages_replayed += result.messages_replayed

        return DLQReplayWorkflowResult(
            total_messages_replayed=total_messages_replayed,
            partition_results=partition_results,
        )

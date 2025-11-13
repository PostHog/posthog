import json
import asyncio
from datetime import timedelta

from temporalio import common, workflow
from temporalio.workflow import ParentClosePolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.delete_recordings.activities import (
    delete_recording_blocks,
    group_recording_blocks,
    load_recording_blocks,
    load_recordings_with_person,
)
from posthog.temporal.delete_recordings.types import (
    Recording,
    RecordingBlockGroup,
    RecordingsWithPersonInput,
    RecordingWithBlocks,
)
from posthog.temporal.delete_recordings.utils import batched


@workflow.defn(name="delete-recording")
class DeleteRecordingWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> Recording:
        """Parse input from the management command CLI."""
        loaded = json.loads(input[0])
        return Recording(**loaded)

    @workflow.run
    async def run(self, input: Recording) -> None:
        recording_input = Recording(session_id=input.session_id, team_id=input.team_id)

        recording_blocks = await workflow.execute_activity(
            load_recording_blocks,
            recording_input,
            start_to_close_timeout=timedelta(minutes=5),
            schedule_to_close_timeout=timedelta(hours=3),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
        )

        if len(recording_blocks) > 0:
            block_groups: list[RecordingBlockGroup] = await workflow.execute_activity(
                group_recording_blocks,
                RecordingWithBlocks(recording=recording_input, blocks=recording_blocks),
                start_to_close_timeout=timedelta(minutes=1),
                schedule_to_close_timeout=timedelta(hours=3),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=2,
                    initial_interval=timedelta(minutes=1),
                ),
            )

            async with asyncio.TaskGroup() as delete_blocks:
                for group in block_groups:
                    delete_blocks.create_task(
                        workflow.execute_activity(
                            delete_recording_blocks,
                            group,
                            start_to_close_timeout=timedelta(minutes=30),
                            schedule_to_close_timeout=timedelta(hours=3),
                            retry_policy=common.RetryPolicy(
                                maximum_attempts=2,
                                initial_interval=timedelta(minutes=1),
                            ),
                        )
                    )


@workflow.defn(name="delete-recordings-with-person")
class DeleteRecordingsWithPersonWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> RecordingsWithPersonInput:
        """Parse input from the management command CLI."""
        loaded = json.loads(input[0])
        return RecordingsWithPersonInput(**loaded)

    @workflow.run
    async def run(self, input: RecordingsWithPersonInput) -> None:
        session_ids = await workflow.execute_activity(
            load_recordings_with_person,
            RecordingsWithPersonInput(distinct_ids=input.distinct_ids, team_id=input.team_id),
            start_to_close_timeout=timedelta(minutes=5),
            schedule_to_close_timeout=timedelta(hours=3),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
        )

        for batch in batched(session_ids, input.batch_size):
            async with asyncio.TaskGroup() as delete_recordings:
                for session_id in batch:
                    delete_recordings.create_task(
                        workflow.execute_child_workflow(
                            DeleteRecordingWorkflow.run,
                            Recording(session_id=session_id, team_id=input.team_id),
                            parent_close_policy=ParentClosePolicy.ABANDON,
                            execution_timeout=timedelta(hours=3),
                            run_timeout=timedelta(hours=1),
                            task_timeout=timedelta(minutes=30),
                            retry_policy=common.RetryPolicy(
                                maximum_attempts=2,
                                initial_interval=timedelta(minutes=1),
                            ),
                        )
                    )

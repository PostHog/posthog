import json
import asyncio
from datetime import timedelta

from temporalio import common, workflow
from temporalio.workflow import ParentClosePolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.delete_recordings.activities import (
    delete_recording_blocks,
    load_recording_blocks,
    load_recordings_with_person,
)
from posthog.temporal.delete_recordings.types import (
    DeleteRecordingBlocksInput,
    RecordingInput,
    RecordingsWithPersonInput,
)


@workflow.defn(name="delete-recording")
class DeleteRecordingWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> RecordingInput:
        """Parse input from the management command CLI."""
        loaded = json.loads(input[0])
        return RecordingInput(**loaded)

    @workflow.run
    async def run(self, input: RecordingInput) -> None:
        recording_input = RecordingInput(session_id=input.session_id, team_id=input.team_id)

        recording_blocks = await workflow.execute_activity(
            load_recording_blocks,
            recording_input,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
            heartbeat_timeout=timedelta(seconds=10),
        )

        await workflow.execute_activity(
            delete_recording_blocks,
            DeleteRecordingBlocksInput(recording=recording_input, blocks=recording_blocks),
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
            heartbeat_timeout=timedelta(seconds=10),
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
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
            heartbeat_timeout=timedelta(seconds=10),
        )

        async with asyncio.TaskGroup() as delete_recordings:
            for session_id in session_ids:
                delete_recordings.create_task(
                    workflow.start_child_workflow(
                        DeleteRecordingWorkflow.run,
                        RecordingInput(session_id=session_id, team_id=input.team_id),
                        parent_close_policy=ParentClosePolicy.ABANDON,
                        execution_timeout=timedelta(minutes=10),
                    )
                )

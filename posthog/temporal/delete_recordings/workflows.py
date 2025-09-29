import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import common, workflow
from temporalio.workflow import ParentClosePolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.delete_recordings.activities import (
    DeleteRecordingBlocksInput,
    LoadRecordingBlocksInput,
    LoadRecordingsWithPersonInput,
    delete_recording_blocks,
    load_recording_blocks,
    load_recordings_with_person,
)


@dataclass(frozen=True)
class DeleteRecordingInput:
    session_id: str
    team_id: int


@workflow.defn(name="delete-recording")
class DeleteRecordingWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> DeleteRecordingInput:
        """Parse input from the management command CLI."""
        loaded = json.loads(input[0])
        return DeleteRecordingInput(**loaded)

    @workflow.run
    async def run(self, input: DeleteRecordingInput) -> None:
        recording_blocks = await workflow.execute_activity(
            load_recording_blocks,
            LoadRecordingBlocksInput(session_id=input.session_id, team_id=input.team_id),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
            heartbeat_timeout=timedelta(seconds=10),
        )

        await workflow.execute_activity(
            delete_recording_blocks,
            DeleteRecordingBlocksInput(session_id=input.session_id, team_id=input.team_id, blocks=recording_blocks),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
            heartbeat_timeout=timedelta(seconds=10),
        )


@dataclass(frozen=True)
class DeleteRecordingsWithPersonInput:
    distinct_ids: list[str]
    team_id: int


@workflow.defn(name="delete-recordings-with-person")
class DeleteRecordingsWithPersonWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> DeleteRecordingsWithPersonInput:
        """Parse input from the management command CLI."""
        loaded = json.loads(input[0])
        return DeleteRecordingsWithPersonInput(**loaded)

    @workflow.run
    async def run(self, input: DeleteRecordingsWithPersonInput) -> None:
        session_ids = await workflow.execute_activity(
            load_recordings_with_person,
            LoadRecordingsWithPersonInput(distinct_ids=input.distinct_ids, team_id=input.team_id),
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
                    workflow.execute_child_workflow(
                        DeleteRecordingWorkflow.run,
                        DeleteRecordingInput(session_id=session_id, team_id=input.team_id),
                        parent_close_policy=ParentClosePolicy.ABANDON,
                        execution_timeout=timedelta(minutes=1),
                    )
                )

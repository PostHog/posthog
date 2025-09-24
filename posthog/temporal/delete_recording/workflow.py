import json
from dataclasses import dataclass
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.delete_recording.activities import (
    DeleteRecordingBlocksInput,
    LoadRecordingBlocksInput,
    delete_recording_blocks,
    load_recording_blocks,
)


@dataclass(frozen=True)
class DeleteRecordingInput:
    session_id: str
    team_id: int


@workflow.defn(name="delete-recordings")
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
            heartbeat_timeout=timedelta(minutes=2),
        )

        await workflow.execute_activity(
            delete_recording_blocks,
            DeleteRecordingBlocksInput(blocks=recording_blocks),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
            heartbeat_timeout=timedelta(minutes=2),
        )

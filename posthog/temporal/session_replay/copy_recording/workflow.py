from datetime import timedelta

from temporalio import common, workflow
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.session_replay.copy_recording.activities import copy_session_recording
from posthog.temporal.session_replay.copy_recording.types import (
    CopyRecordingsInput,
    CopyRecordingsResult,
    CopySessionInput,
    CopySessionResult,
)


@workflow.defn(name="copy-recordings")
class CopyRecordingsWorkflow(PostHogWorkflow):
    """Copies recordings from one team to another, for example to seed a demo project."""

    inputs_cls = CopyRecordingsInput

    @workflow.run
    async def run(self, input: CopyRecordingsInput) -> CopyRecordingsResult:
        sessions: list[CopySessionResult] = []
        for session_id in input.session_ids:
            try:
                result: CopySessionResult = await workflow.execute_activity(
                    copy_session_recording,
                    CopySessionInput(
                        source_team_id=input.source_team_id,
                        target_team_id=input.target_team_id,
                        session_id=session_id,
                        retention_days=input.retention_days,
                    ),
                    start_to_close_timeout=timedelta(minutes=15),
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30)),
                )
            except ActivityError as e:
                result = CopySessionResult(session_id=session_id, status="failed", warnings=[str(e.cause or e)])
            sessions.append(result)
        return CopyRecordingsResult(sessions=sessions)

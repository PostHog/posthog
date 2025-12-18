import json
import asyncio
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.import_recording.activities import (
    build_import_context,
    cleanup_import_data,
    import_event_clickhouse_rows,
    import_recording_data,
    import_replay_clickhouse_rows,
)
from posthog.temporal.import_recording.types import ImportRecordingInput


@workflow.defn(name="import-recording")
class ImportRecordingWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> ImportRecordingInput:
        return ImportRecordingInput(**json.loads(input[0]))

    @workflow.run
    async def run(self, input: ImportRecordingInput) -> None:
        import_context = await workflow.execute_activity(
            build_import_context,
            input,
            start_to_close_timeout=timedelta(minutes=5),
            schedule_to_close_timeout=timedelta(hours=3),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
        )

        async with asyncio.TaskGroup() as import_tasks:
            import_tasks.create_task(
                workflow.execute_activity(
                    import_replay_clickhouse_rows,
                    import_context,
                    start_to_close_timeout=timedelta(minutes=30),
                    schedule_to_close_timeout=timedelta(hours=3),
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=1),
                    ),
                )
            )
            import_tasks.create_task(
                workflow.execute_activity(
                    import_event_clickhouse_rows,
                    import_context,
                    start_to_close_timeout=timedelta(minutes=30),
                    schedule_to_close_timeout=timedelta(hours=3),
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=1),
                    ),
                )
            )
            import_tasks.create_task(
                workflow.execute_activity(
                    import_recording_data,
                    import_context,
                    start_to_close_timeout=timedelta(minutes=30),
                    schedule_to_close_timeout=timedelta(hours=3),
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=1),
                    ),
                )
            )

        await workflow.execute_activity(
            cleanup_import_data,
            import_context,
            start_to_close_timeout=timedelta(minutes=5),
            schedule_to_close_timeout=timedelta(hours=3),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
        )

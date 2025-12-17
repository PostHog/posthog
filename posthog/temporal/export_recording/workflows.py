import os
import json
import asyncio
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.export_recording.activities import (
    build_recording_export_context,
    cleanup_export_data,
    export_event_clickhouse_rows,
    export_recording_data,
    export_recording_data_prefix,
    export_replay_clickhouse_rows,
    store_export_data,
)
from posthog.temporal.export_recording.types import ExportRecordingInput, RedisConfig


@workflow.defn(name="export-recording")
class ExportRecordingWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> ExportRecordingInput:
        return ExportRecordingInput(**json.loads(input[0]))

    @workflow.run
    async def run(self, input: ExportRecordingInput) -> None:
        if input.redis_config.redis_host == RedisConfig().redis_host:
            input.redis_config.redis_host = os.getenv("EXPORT_RECORDING_REDIS_HOST", "localhost")

        if input.redis_config.redis_port == RedisConfig().redis_port:
            input.redis_config.redis_port = int(os.getenv("EXPORT_RECORDING_REDIS_PORT", "6379"))

        export_context = await workflow.execute_activity(
            build_recording_export_context,
            input,
            start_to_close_timeout=timedelta(minutes=5),
            schedule_to_close_timeout=timedelta(hours=3),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
        )

        async with asyncio.TaskGroup() as export_tasks:
            export_tasks.create_task(
                workflow.execute_activity(
                    export_replay_clickhouse_rows,
                    export_context,
                    start_to_close_timeout=timedelta(minutes=30),
                    schedule_to_close_timeout=timedelta(hours=3),
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=1),
                    ),
                )
            )
            export_tasks.create_task(
                workflow.execute_activity(
                    export_event_clickhouse_rows,
                    export_context,
                    start_to_close_timeout=timedelta(minutes=30),
                    schedule_to_close_timeout=timedelta(hours=3),
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=1),
                    ),
                )
            )
            export_tasks.create_task(
                workflow.execute_activity(
                    export_recording_data,
                    export_context,
                    start_to_close_timeout=timedelta(minutes=30),
                    schedule_to_close_timeout=timedelta(hours=3),
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=1),
                    ),
                )
            )
            export_tasks.create_task(
                workflow.execute_activity(
                    export_recording_data_prefix,
                    export_context,
                    start_to_close_timeout=timedelta(minutes=5),
                    schedule_to_close_timeout=timedelta(hours=3),
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=1),
                    ),
                )
            )

        await workflow.execute_activity(
            store_export_data,
            export_context,
            start_to_close_timeout=timedelta(minutes=30),
            schedule_to_close_timeout=timedelta(hours=3),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
        )

        await workflow.execute_activity(
            cleanup_export_data,
            export_context,
            start_to_close_timeout=timedelta(minutes=5),
            schedule_to_close_timeout=timedelta(hours=3),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
        )

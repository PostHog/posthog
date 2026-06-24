import asyncio
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.session_replay.export_recording.activities import (
    build_recording_export_context,
    cleanup_export_data,
    export_event_clickhouse_rows,
    export_recording_data,
    export_recording_data_prefix,
    export_replay_clickhouse_rows,
    mark_export_failed,
    store_export_data,
)
from posthog.temporal.session_replay.export_recording.types import ExportRecordingInput, MarkExportFailedInput


@workflow.defn(name="export-recording")
class ExportRecordingWorkflow(PostHogWorkflow):
    inputs_cls = ExportRecordingInput

    @workflow.run
    async def run(self, input: ExportRecordingInput) -> None:
        try:
            await self._export(input)
        except Exception as e:
            # the export status is set to RUNNING up front and only flipped to COMPLETE on the
            # happy path. Without this, a failed/timed-out export sits in RUNNING forever. Record
            # the failure on the row, then re-raise so Temporal still marks the workflow failed.
            # asyncio.TaskGroup wraps a failing parallel activity in an ExceptionGroup whose str()
            # is generic, so surface the underlying messages instead.
            message = "; ".join(str(sub) for sub in e.exceptions) if isinstance(e, BaseExceptionGroup) else str(e)
            try:
                await workflow.execute_activity(
                    mark_export_failed,
                    MarkExportFailedInput(exported_recording_id=input.exported_recording_id, error_message=message),
                    start_to_close_timeout=timedelta(minutes=1),
                    schedule_to_close_timeout=timedelta(minutes=10),
                    retry_policy=common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5)),
                )
            except Exception:
                # don't let a failure to record the failure mask the original error
                workflow.logger.exception("Failed to mark export as failed")
            raise

    async def _export(self, input: ExportRecordingInput) -> None:
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
                    start_to_close_timeout=timedelta(hours=3),
                    schedule_to_close_timeout=timedelta(hours=6),
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
            start_to_close_timeout=timedelta(hours=3),
            schedule_to_close_timeout=timedelta(hours=6),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
        )

        try:
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
        except Exception:
            # cleanup only frees Redis keys that already carry a TTL, and it runs after the export
            # is uploaded and marked COMPLETE. A failure here must not fail an otherwise-good export.
            workflow.logger.warning("Export cleanup failed; Redis keys will expire via their TTL")

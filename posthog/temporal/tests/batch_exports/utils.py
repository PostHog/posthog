import asyncio
import uuid

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import create_batch_export_run
from posthog.temporal.batch_exports.batch_exports import StartBatchExportRunInputs


@activity.defn(name="start_batch_export_run")
async def mocked_start_batch_export_run(inputs: StartBatchExportRunInputs) -> str:
    """Create a run and return some count >0 to avoid early return."""
    run = await sync_to_async(create_batch_export_run)(
        batch_export_id=uuid.UUID(inputs.batch_export_id),
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        status=BatchExportRun.Status.STARTING,
    )

    return str(run.id)


async def get_record_batch_from_queue(queue, produce_task):
    while not queue.empty() or not produce_task.done():
        try:
            record_batch = queue.get_nowait()
        except asyncio.QueueEmpty:
            if produce_task.done():
                break
            else:
                await asyncio.sleep(0)
                continue

        return record_batch
    return None

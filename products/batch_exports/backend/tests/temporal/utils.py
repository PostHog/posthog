import asyncio
import collections.abc
import typing
import uuid

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import create_batch_export_run
from posthog.temporal.common.asyncpa import InvalidMessageFormat
from posthog.temporal.common.clickhouse import ClickHouseClient
from products.batch_exports.backend.temporal.batch_exports import (
    StartBatchExportRunInputs,
)
from products.batch_exports.backend.temporal.spmc import slice_record_batch


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


class FlakyClickHouseClient(ClickHouseClient):
    """Fake ClickHouseClient that simulates a failure after reading a certain number of records.

    Raises a `InvalidMessageFormat` exception after reading a certain number of records.
    This is an error we've seen in production.
    """

    def __init__(self, *args, fail_after_records, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_after_records = fail_after_records

    async def astream_query_as_arrow(self, *args, **kwargs):
        count = 0
        async for batch in super().astream_query_as_arrow(*args, **kwargs):
            # guarantees one record per batch
            for sliced_batch in slice_record_batch(batch, max_record_batch_size_bytes=1, min_records_per_batch=1):
                count += 1
                if count > self.fail_after_records:
                    raise InvalidMessageFormat("Simulated failure")
                yield sliced_batch


def remove_duplicates_from_records(
    records: list[dict[str, typing.Any]], key: collections.abc.Sequence[str] | None = None
) -> list[dict[str, typing.Any]]:
    """Remove duplicates from a list of records.

    Used in batch exports testing when we expect a number of duplicates not known
    beforehand to be present in the results. Since we can't know how many duplicates
    there are, and which exact records will be duplicated, we remove them so that
    comparisons won't fail.
    """
    if not key:
        dedup_key: tuple[str, ...] = ("uuid",)
    else:
        dedup_key = tuple(key)

    seen = set()

    def is_record_seen(record: dict[str, typing.Any]) -> bool:
        nonlocal seen

        pk = tuple(record[k] for k in dedup_key)

        if pk in seen:
            return True

        seen.add(pk)
        return False

    inserted_records = [record for record in records if not is_record_seen(record)]

    return inserted_records

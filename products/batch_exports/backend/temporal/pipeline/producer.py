import typing
import asyncio

from django.conf import settings

from aiobotocore.response import StreamingBody

import posthog.temporal.common.asyncpa as asyncpa
from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.temporal.pipeline.internal_stage import get_base_s3_staging_folder, get_s3_client
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, slice_record_batch
from products.batch_exports.backend.temporal.utils import make_retryable_with_exponential_backoff

if typing.TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client


LOGGER = get_write_only_logger(__name__)


class Producer:
    """
    Async producer that reads data from the internal S3 staging area for a given batch export and puts the data into a
    provided queue.
    """

    def __init__(self):
        self.logger = LOGGER.bind()
        self._task: asyncio.Task | None = None

    @property
    def task(self) -> asyncio.Task:
        if self._task is None:
            raise ValueError("Producer task is not initialized, have you called `Producer.start()`?")
        return self._task

    async def start(
        self,
        queue: RecordBatchQueue,
        batch_export_id: str,
        data_interval_start: str | None,
        data_interval_end,
        max_record_batch_size_bytes: int = 0,
        min_records_per_batch: int = 100,
        # TODO: after deployment, make this required
        stage_folder: str | None = None,
    ) -> asyncio.Task:
        self._task = asyncio.create_task(
            self.produce_batch_export_record_batches_from_range(
                queue=queue,
                batch_export_id=batch_export_id,
                data_interval_start=data_interval_start,
                data_interval_end=data_interval_end,
                max_record_batch_size_bytes=max_record_batch_size_bytes,
                min_records_per_batch=min_records_per_batch,
                stage_folder=stage_folder,
            ),
            name="record_batch_producer",
        )
        return self._task

    async def produce_batch_export_record_batches_from_range(
        self,
        queue: RecordBatchQueue,
        batch_export_id: str,
        data_interval_start: str | None,
        data_interval_end: str,
        max_record_batch_size_bytes: int = 0,
        min_records_per_batch: int = 100,
        stage_folder: str | None = None,
    ):
        # TODO: after deployment, remove the fallback behaviour.
        if stage_folder is None:
            stage_folder = get_base_s3_staging_folder(
                batch_export_id=batch_export_id,
                data_interval_start=data_interval_start,
                data_interval_end=data_interval_end,
            )
        async with get_s3_client() as s3_client:
            response = await s3_client.list_objects_v2(
                Bucket=settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET, Prefix=stage_folder
            )
            if not (contents := response.get("Contents", [])):
                self.logger.info(f"No files found in S3 with prefix '{stage_folder}' -> assuming no data to export")
                return
            keys = [obj["Key"] for obj in contents if "Key" in obj]
            self.logger.info(f"Producer found {len(keys)} files in S3 stage, with prefix '{stage_folder}'")

            # Read in batches
            try:
                await self._stream_record_batches_from_s3(
                    s3_client, keys, queue, max_record_batch_size_bytes, min_records_per_batch
                )
            except Exception as e:
                self.logger.exception("Unexpected error occurred while producing record batches", exc_info=e)
                raise

    async def _stream_record_batches_from_s3(
        self,
        s3_client: "S3Client",
        keys: list[str],
        queue: RecordBatchQueue,
        max_record_batch_size_bytes: int = 0,
        min_records_per_batch: int = 100,
    ):
        async def stream_from_s3_file(key):
            self.logger.info("Starting stream", key=key)

            s3_ob = await s3_client.get_object(Bucket=settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET, Key=key)
            assert "Body" in s3_ob, "Body not found in S3 object"
            stream: StreamingBody = s3_ob["Body"]
            # read in 128KB chunks of data from S3
            reader = asyncpa.AsyncRecordBatchReader(stream.iter_chunks(chunk_size=128 * 1024))

            async for batch in reader:
                for record_batch_slice in slice_record_batch(batch, max_record_batch_size_bytes, min_records_per_batch):
                    await queue.put(record_batch_slice)

            self.logger.info("Finished stream", key=key)

        async with asyncio.TaskGroup() as tg:
            stream_func = make_retryable_with_exponential_backoff(
                stream_from_s3_file, max_attempts=5, max_retry_delay=1
            )
            for key in keys:
                tg.create_task(stream_func(key))

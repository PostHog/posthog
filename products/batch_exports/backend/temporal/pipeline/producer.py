import typing
import asyncio
import dataclasses

from django.conf import settings

import pyarrow as pa
from aiobotocore.response import StreamingBody
from opentelemetry import trace

import posthog.temporal.common.asyncpa as asyncpa
from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.temporal.metrics import CumulativeTimer
from products.batch_exports.backend.temporal.pipeline.internal_stage import get_base_s3_staging_folder, get_s3_client
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, slice_record_batch
from products.batch_exports.backend.temporal.utils import make_retryable_with_exponential_backoff

if typing.TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client


LOGGER = get_write_only_logger(__name__)
TRACER = trace.get_tracer(__name__)


@dataclasses.dataclass
class S3FileResumeState:
    """Tracks how far into an S3 staging file we have fully enqueued record batches.

    Used to resume from the last record batch boundary when retrying a failed
    read, instead of re-reading (and re-emitting) the whole file.

    Attributes:
        offset: Absolute byte offset of the next unread IPC message.
        schema: Cached schema, so a resumed stream (which lacks the schema
            message) can be parsed.
        object_size: Full object size.
        etag: Object ETag so a resumed range GET can assert (via IfMatch) it is
            reading the same object, and fail loudly with a 412 if not.
    """

    offset: int
    schema: pa.Schema | None
    object_size: int
    etag: str


class Producer:
    """
    Async producer that reads data from the internal S3 staging area for a given batch export and puts the data into a
    provided queue.
    """

    def __init__(self):
        self.logger = LOGGER.bind()
        self._task: asyncio.Task | None = None

        # Stage-attribution counters, reported as span attributes. The put-wait timer sums the
        # time readers spend blocked on `queue.put()` (i.e. downstream backpressure).
        # Note: since we have up to BATCH_EXPORT_PRODUCER_MAX_CONCURRENT_FILE_READS concurrent
        # readers this is cumulative task-seconds and can exceed wall-clock time.
        self._queue_put_wait_timer = CumulativeTimer()
        self.records_produced: int = 0
        self.bytes_produced: int = 0

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
        with TRACER.start_as_current_span("batch_export.producer") as span:
            async with get_s3_client() as s3_client:
                try:
                    keys = await self._list_keys(s3_client, stage_folder)
                    span.set_attribute("batch_export.producer.num_files", len(keys))
                    if not keys:
                        return

                    # Read in batches
                    await self._stream_record_batches_from_s3(
                        s3_client, keys, queue, max_record_batch_size_bytes, min_records_per_batch
                    )
                except Exception as e:
                    self.logger.exception("Unexpected error occurred while producing record batches", exc_info=e)
                    raise
                finally:
                    span.set_attributes(
                        {
                            "batch_export.producer.records_produced": self.records_produced,
                            "batch_export.producer.bytes_produced": self.bytes_produced,
                            "batch_export.producer.total_queue_put_wait_seconds": self._queue_put_wait_timer.total_seconds,
                        }
                    )

    async def _list_keys(self, s3_client: "S3Client", stage_folder: str) -> list[str]:
        response = await s3_client.list_objects_v2(
            Bucket=settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET, Prefix=stage_folder
        )
        if not (contents := response.get("Contents", [])):
            self.logger.info(f"No files found in S3 with prefix '{stage_folder}' -> assuming no data to export")
            return []
        keys = [obj["Key"] for obj in contents if "Key" in obj]
        self.logger.info(f"Producer found {len(keys)} files in S3 stage, with prefix '{stage_folder}'")
        return keys

    async def _resume_staging_file(
        self, s3_client: "S3Client", key: str, state: S3FileResumeState
    ) -> StreamingBody | None:
        """Resume the S3 staging file for `key` from `state`.

        Returns the remaining byte stream to read resuming from `state` as
        returned by `_open_staging_file` or `None` if the `state` indicates that
        the file was already fully consumed.
        """
        if state.offset >= state.object_size:
            # Defensive: a previous attempt consumed every batch (e.g. the file lacks
            # an EOS marker); a range GET here would fail with 416 InvalidRange.
            self.logger.info("Stream already fully consumed, nothing to resume", key=key, offset=state.offset)
            return None

        self.logger.info("Resuming stream after retryable failure", key=key, offset=state.offset)
        # `IfMatch` guards against the object changing under us: staging files are write-once
        # today, but if that ever changes, ranging into a different object fails with a 412
        # instead of silently yielding the wrong data.
        s3_ob = await s3_client.get_object(
            Bucket=settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET,
            Key=key,
            Range=f"bytes={state.offset}-",
            IfMatch=state.etag,
        )

        assert "Body" in s3_ob, "Body not found in S3 object"

        return s3_ob["Body"]

    async def _open_staging_file(self, s3_client: "S3Client", key: str) -> tuple[StreamingBody, S3FileResumeState]:
        """Open the S3 staging file for `key`.

        Returns the full byte stream to read, as well as the initial state
        required to eventually resume this byte stream in case we fail part way
        through.
        """
        self.logger.info("Starting stream", key=key)
        s3_ob = await s3_client.get_object(Bucket=settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET, Key=key)

        assert "Body" in s3_ob, "Body not found in S3 object"

        return s3_ob["Body"], S3FileResumeState(
            offset=0, schema=None, object_size=s3_ob["ContentLength"], etag=s3_ob["ETag"]
        )

    async def _stream_record_batches_from_s3(
        self,
        s3_client: "S3Client",
        keys: list[str],
        queue: RecordBatchQueue,
        max_record_batch_size_bytes: int = 0,
        min_records_per_batch: int = 100,
    ):
        # Per-key resume state, surviving across retries of `stream_from_s3_file` so a retry
        # continues from the last fully-enqueued record batch instead of re-emitting duplicates.
        resume_states: dict[str, S3FileResumeState] = {}

        async def stream_from_s3_file(key: str) -> None:
            is_starting = key not in resume_states or resume_states[key].offset == 0

            if is_starting:
                stream, new_state = await self._open_staging_file(s3_client, key)
                resume_states[key] = new_state

            else:
                maybe_stream = await self._resume_staging_file(s3_client, key, resume_states[key])
                if maybe_stream is None:
                    return

                stream = maybe_stream

            state = resume_states[key]
            base_offset = state.offset

            reader = asyncpa.AsyncRecordBatchReader(
                stream.iter_chunks(chunk_size=128 * 1024),  # 128 KiB
                # Schema will be set on the state if we managed to fully read and
                # enqueue at least one batch before failing and retrying. This is
                # required as the schema message is only present at the start.
                schema=state.schema,
            )

            async for batch in reader:
                for record_batch_slice in slice_record_batch(batch, max_record_batch_size_bytes, min_records_per_batch):
                    with self._queue_put_wait_timer.time():
                        await queue.put(record_batch_slice)
                    self.records_produced += record_batch_slice.num_rows
                    self.bytes_produced += record_batch_slice.nbytes

                # Only advance the resume point once every slice of this batch is enqueued.
                state.offset = base_offset + reader.bytes_consumed
                if not state.schema:
                    state.schema = reader.schema

            self.logger.info("Finished stream", key=key)

        stream_func = make_retryable_with_exponential_backoff(stream_from_s3_file, max_attempts=5, max_retry_delay=1)

        # Bound how many files we read at once (so S3 connections and in-flight memory stay bounded as
        # the file count grows with export size).
        semaphore = asyncio.Semaphore(settings.BATCH_EXPORT_PRODUCER_MAX_CONCURRENT_FILE_READS)

        async def stream_with_semaphore(key):
            try:
                await stream_func(key)
            finally:
                semaphore.release()

        async with asyncio.TaskGroup() as tg:
            for key in keys:
                await semaphore.acquire()
                tg.create_task(stream_with_semaphore(key))

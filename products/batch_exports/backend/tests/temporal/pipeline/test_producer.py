import io
import uuid
import random
import string
import typing
import asyncio
import datetime as dt
import functools
import contextlib
import collections

import pytest
from unittest.mock import patch

from django.conf import settings
from django.test.utils import override_settings

import pyarrow as pa

from posthog.temporal.common import asyncpa
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse

from products.batch_exports.backend.service import BatchExportModel
from products.batch_exports.backend.temporal.pipeline import producer as producer_module
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)
from products.batch_exports.backend.temporal.pipeline.producer import Producer, S3FileResumeState
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, wait_for_schema_or_producer
from products.batch_exports.backend.temporal.utils import make_retryable_with_exponential_backoff
from products.batch_exports.backend.tests.temporal.utils.s3 import assert_files_in_s3

if typing.TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client

pytestmark = [pytest.mark.asyncio]

# The producer reads S3 objects in chunks of this size, so test objects must be larger for a
# mid-file failure to be observable.
PRODUCER_CHUNK_SIZE = 128 * 1024
FAKE_ETAG = '"fake-etag"'


class FakeStreamingBody:
    def __init__(self, data: bytes, fail_after_bytes: int | None = None) -> None:
        self._data = data
        self._fail_after_bytes = fail_after_bytes

    def iter_chunks(self, chunk_size: int):
        async def chunks():
            position = 0
            while position < len(self._data):
                if self._fail_after_bytes is not None and position >= self._fail_after_bytes:
                    raise ConnectionResetError("Simulated mid-stream failure")

                yield self._data[position : position + chunk_size]
                position += chunk_size

        return chunks()


class FakeS3Client:
    """In-memory S3 client that can fail chosen read attempts and honors Range/IfMatch."""

    def __init__(self, objects: dict[str, bytes], fail_after_bytes_per_attempt: list[int | None] | None = None) -> None:
        self._objects = objects
        # Index i is the byte offset (into attempt i's returned body) at which that read fails, or None.
        self._fail_after_bytes_per_attempt = fail_after_bytes_per_attempt or []
        self._get_counts: collections.Counter[str] = collections.Counter()
        self.get_object_requests: list[tuple[str, str | None, str | None]] = []

    async def get_object(self, Bucket: str, Key: str, Range: str | None = None, IfMatch: str | None = None) -> dict:
        attempt = self._get_counts[Key]
        self._get_counts[Key] += 1
        self.get_object_requests.append((Key, Range, IfMatch))

        offset = int(Range.removeprefix("bytes=").removesuffix("-")) if Range is not None else 0
        assert offset < len(self._objects[Key]), "Invalid range requested"

        fail_after_bytes = (
            self._fail_after_bytes_per_attempt[attempt] if attempt < len(self._fail_after_bytes_per_attempt) else None
        )
        return {
            "Body": FakeStreamingBody(self._objects[Key][offset:], fail_after_bytes),
            "ContentLength": len(self._objects[Key]) - offset,
            "ETag": FAKE_ETAG,
        }


def generate_arrow_ipc_file(
    total_batches: int = 5, rows_per_batch: int = 10, text_size_bytes: int = 10 * 1024
) -> tuple[list[pa.RecordBatch], bytes]:
    batches = []
    for batch_number in range(total_batches):
        records = [
            {
                "id": row + batch_number * rows_per_batch,
                "text": "".join(random.choices(string.ascii_letters, k=text_size_bytes)),
            }
            for row in range(rows_per_batch)
        ]
        batches.append(pa.RecordBatch.from_pylist(records))

    buffer = io.BytesIO()
    with pa.ipc.new_stream(buffer, schema=batches[0].schema) as writer:
        for batch in batches:
            writer.write_batch(batch)

    return batches, buffer.getvalue()


async def record_batch_end_offsets(ipc_bytes: bytes) -> list[int]:
    """Absolute byte offset after each record batch message, as the producer would resume from."""
    reader = asyncpa.AsyncRecordBatchReader(FakeStreamingBody(ipc_bytes).iter_chunks(PRODUCER_CHUNK_SIZE))
    offsets = []
    async for _ in reader:
        offsets.append(reader.bytes_consumed)
    return offsets


def drain(queue: RecordBatchQueue) -> list[pa.RecordBatch]:
    consumed = []
    while not queue.empty():
        consumed.append(queue.get_nowait())
    return consumed


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        producer_module,
        "make_retryable_with_exponential_backoff",
        functools.partial(make_retryable_with_exponential_backoff, initial_retry_delay=0, max_delay_jitter=0),
    )


@pytest.mark.parametrize("fail_after_bytes", [0, PRODUCER_CHUNK_SIZE])
async def test_stream_record_batches_from_s3_resumes_after_mid_file_failure(fail_after_bytes: int):
    batches, ipc_bytes = generate_arrow_ipc_file()
    assert len(ipc_bytes) > PRODUCER_CHUNK_SIZE

    key = "batch-export-data/file_0.arrow"
    fake_s3_client = FakeS3Client({key: ipc_bytes}, fail_after_bytes_per_attempt=[fail_after_bytes])
    queue = RecordBatchQueue()
    producer = Producer()

    # keep mypy happy
    s3_client = typing.cast("S3Client", fake_s3_client)
    await producer._stream_record_batches_from_s3(s3_client, [key], queue)

    expected_table = pa.Table.from_batches(batches)
    assert pa.Table.from_batches(drain(queue), schema=expected_table.schema).equals(expected_table)
    assert producer.records_produced == expected_table.num_rows

    assert len(fake_s3_client.get_object_requests) == 2
    retry_key, retry_range, retry_if_match = fake_s3_client.get_object_requests[1]
    assert retry_key == key

    if fail_after_bytes == 0:
        # Failed before any batch was enqueued: the retry must re-read the whole file.
        assert retry_range is None
        assert retry_if_match is None
    else:
        assert retry_range is not None
        offset = int(retry_range.removeprefix("bytes=").removesuffix("-"))
        assert 0 < offset < len(ipc_bytes)
        # The resume offset must land on an IPC message boundary, past the schema message.
        assert ipc_bytes[offset : offset + 4] == asyncpa.CONTINUATION_BYTES
        # And it must pin the object it was resuming so a swapped object fails loudly.
        assert retry_if_match == FAKE_ETAG


async def test_stream_record_batches_from_s3_resumes_across_multiple_failures():
    batches, ipc_bytes = generate_arrow_ipc_file()
    offsets = await record_batch_end_offsets(ipc_bytes)
    assert len(offsets) >= 3

    key = "batch-export-data/file_0.arrow"
    # Fail the first two reads after a single chunk each (~one batch), so every retry resumes
    # from a strictly greater offset than the last and the read completes on the third attempt.
    fake_s3_client = FakeS3Client({key: ipc_bytes}, fail_after_bytes_per_attempt=[1, 1])
    queue = RecordBatchQueue()
    producer = Producer()

    # keep mypy happy
    s3_client = typing.cast("S3Client", fake_s3_client)
    await producer._stream_record_batches_from_s3(s3_client, [key], queue)

    expected_table = pa.Table.from_batches(batches)
    assert pa.Table.from_batches(drain(queue), schema=expected_table.schema).equals(expected_table)
    assert producer.records_produced == expected_table.num_rows

    # Initial read plus two resumes, each from the boundary the previous attempt reached.
    ranges = [(rng, if_match) for _, rng, if_match in fake_s3_client.get_object_requests]
    assert ranges == [
        (None, None),
        (f"bytes={offsets[0]}-", FAKE_ETAG),
        (f"bytes={offsets[1]}-", FAKE_ETAG),
    ]


async def test_open_staging_file_short_circuits_when_fully_consumed():
    key = "batch-export-data/file_0.arrow"
    _, ipc_bytes = generate_arrow_ipc_file(total_batches=1)
    fake_s3_client = FakeS3Client({key: ipc_bytes})
    producer = Producer()

    # Resume state that has already consumed the whole object: a range GET would 416.
    state = S3FileResumeState(
        offset=len(ipc_bytes),
        schema=pa.schema([("id", pa.int64()), ("text", pa.string())]),
        object_size=len(ipc_bytes),
        etag=FAKE_ETAG,
    )
    # keep mypy happy
    s3_client = typing.cast("S3Client", fake_s3_client)
    stream = await producer._open_staging_file(s3_client, key, state)

    assert stream is None
    assert fake_s3_client.get_object_requests == []


class _FailOnceStreamingBody:
    """Wraps a real S3 streaming body so a read fails partway through, once.

    Emits the body in `emit_chunk_size` pieces (ignoring the producer's requested chunk size) and
    raises immediately after emitting `fail_after_bytes`. With `fail_after_bytes` set between two
    record batch boundaries, the reader consumes and enqueues the earlier batches before the failure
    but not the later ones, so the retry must resume mid-file.
    """

    def __init__(self, body, fail_after_bytes: int, emit_chunk_size: int) -> None:
        self._body = body
        self._fail_after_bytes = fail_after_bytes
        self._emit_chunk_size = emit_chunk_size

    def iter_chunks(self, chunk_size: int):
        async def chunks():
            data = await self._body.read()
            emitted = 0
            for start in range(0, len(data), self._emit_chunk_size):
                piece = data[start : start + self._emit_chunk_size]
                yield piece
                emitted += len(piece)
                if emitted >= self._fail_after_bytes:
                    raise ConnectionResetError("Simulated mid-stream failure")

        return chunks()


class _FailFirstReadS3Client:
    """Delegates to a real S3 client, failing only the body of the first get_object per client."""

    def __init__(self, real_client, fail_after_bytes: int, emit_chunk_size: int) -> None:
        self._real = real_client
        self._fail_after_bytes = fail_after_bytes
        self._emit_chunk_size = emit_chunk_size
        self._get_object_count = 0
        self.get_object_calls: list[dict] = []

    async def list_objects_v2(self, **kwargs):
        return await self._real.list_objects_v2(**kwargs)

    async def get_object(self, **kwargs):
        self._get_object_count += 1
        self.get_object_calls.append(kwargs)
        response = await self._real.get_object(**kwargs)
        if self._get_object_count == 1:
            response["Body"] = _FailOnceStreamingBody(response["Body"], self._fail_after_bytes, self._emit_chunk_size)
        return response


async def _drain_stage_via_producer(
    stage_folder: str, data_interval_start: dt.datetime, data_interval_end: dt.datetime
) -> list[dict]:
    """Run the real producer over the internal stage and collect every emitted row."""
    queue = RecordBatchQueue()
    producer = Producer()
    producer_task = await producer.start(
        queue=queue,
        batch_export_id=str(uuid.uuid4()),
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        stage_folder=stage_folder,
    )
    await wait_for_schema_or_producer(queue, producer_task)

    rows: list[dict] = []
    while True:
        try:
            rows.extend(queue.get_nowait().to_pylist())
        except asyncio.QueueEmpty:
            if producer_task.done():
                break
            await asyncio.sleep(0.1)

    # Surface a producer failure rather than a confusing row-count mismatch.
    await producer_task
    return rows


@pytest.mark.django_db
@pytest.mark.parametrize("interval", ["day"], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="events", schema=None)])
async def test_producer_resumes_from_offset_after_mid_file_failure(
    interval,
    activity_environment,
    data_interval_start,
    data_interval_end,
    minio_client,
    ateam,
    clickhouse_client,
    model: BatchExportModel,
):
    """A mid-file read failure resumes from the last batch boundary instead of re-delivering rows."""

    # ClickHouse writes one Arrow record batch per source block, so several separate inserts (plus a
    # tiny insert-block size to prevent coalescing) yield a staging file with several record batches.
    num_inserts = 10
    events_per_insert = 100
    for n in range(num_inserts):
        await generate_test_events_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=data_interval_start,
            end_time=data_interval_end,
            count=events_per_insert,
            count_outside_range=0,
            count_other_team=0,
            event_name=f"resume-test-{n}-{{i}}",
            table="events_recent",
        )
    total_events = num_inserts * events_per_insert

    insert_inputs = BatchExportInsertIntoInternalStageInputs(
        team_id=ateam.pk,
        batch_export_id=str(uuid.uuid4()),
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=None,
        include_events=None,
        run_id=None,
        batch_export_schema=None,
        batch_export_model=model,
        backfill_details=None,
        destination_default_fields=None,
    )
    with override_settings(
        BATCH_EXPORT_DYNAMIC_PARTITIONING_ENABLED=False,
        BATCH_EXPORT_CLICKHOUSE_S3_PARTITIONS=1,
        BATCH_EXPORTS_CLICKHOUSE_MAX_INSERT_BLOCK_SIZE_BYTES=1,
    ):
        stage_result = await activity_environment.run(insert_into_internal_stage_activity, insert_inputs)
    stage_folder = stage_result.stage_folder

    _, keys = await assert_files_in_s3(
        minio_client,
        bucket_name=settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET,
        key_prefix=stage_folder,
        file_format="Arrow",
        compression=None,
        json_columns=None,
    )
    assert len(keys) == 1
    key = keys[0]

    file_response = await minio_client.get_object(Bucket=settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET, Key=key)
    file_bytes = await file_response["Body"].read()
    offsets = await record_batch_end_offsets(file_bytes)
    assert len(offsets) > 1, "test needs a multi-record-batch file to exercise resume"

    # Fail in the last record batch: at least the first batch is enqueued before the failure, and the
    # last one is not, so the retry must resume from a batch boundary partway through the file. The
    # emit size keeps the failure point strictly between two boundaries regardless of batch sizes.
    fail_after_bytes = (offsets[0] + offsets[-1]) // 2
    emit_chunk_size = max(1, (offsets[-1] - offsets[0]) // 8)

    wrapper: _FailFirstReadS3Client | None = None
    real_get_s3_client = producer_module.get_s3_client

    @contextlib.asynccontextmanager
    async def failing_get_s3_client():
        nonlocal wrapper
        async with real_get_s3_client() as real_client:
            wrapper = _FailFirstReadS3Client(real_client, fail_after_bytes, emit_chunk_size)
            yield wrapper

    with patch.object(producer_module, "get_s3_client", failing_get_s3_client):
        exported_rows = await _drain_stage_via_producer(stage_folder, data_interval_start, data_interval_end)

    # Every event delivered exactly once, despite the mid-file failure (a re-read would duplicate).
    assert len(exported_rows) == total_events
    assert len({row["uuid"] for row in exported_rows}) == total_events

    # The retry resumed with a ranged, ETag-pinned GET rather than re-reading from the start.
    assert wrapper is not None
    assert len(wrapper.get_object_calls) == 2
    resume_call = wrapper.get_object_calls[1]
    assert resume_call.get("Range", "").startswith("bytes=")
    assert int(resume_call["Range"].removeprefix("bytes=").removesuffix("-")) > 0
    assert resume_call.get("IfMatch")

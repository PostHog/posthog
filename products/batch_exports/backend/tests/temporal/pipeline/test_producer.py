import io
import random
import string
import typing
import functools
import collections

import pytest

import pyarrow as pa

from posthog.temporal.common import asyncpa

from products.batch_exports.backend.temporal.pipeline import producer as producer_module
from products.batch_exports.backend.temporal.pipeline.producer import Producer
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue
from products.batch_exports.backend.temporal.utils import make_retryable_with_exponential_backoff

if typing.TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client

pytestmark = [pytest.mark.asyncio]

# The producer reads S3 objects in chunks of this size, so test objects must be larger for a
# mid-file failure to be observable.
PRODUCER_CHUNK_SIZE = 128 * 1024


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
    """In-memory S3 client that fails the body stream of the first GET per key after N bytes."""

    def __init__(self, objects: dict[str, bytes], fail_first_read_after_bytes: int | None = None) -> None:
        self._objects = objects
        self._fail_first_read_after_bytes = fail_first_read_after_bytes
        self._get_counts: collections.Counter[str] = collections.Counter()
        self.get_object_requests: list[tuple[str, str | None]] = []

    async def get_object(self, Bucket: str, Key: str, Range: str | None = None) -> dict:
        self.get_object_requests.append((Key, Range))
        self._get_counts[Key] += 1

        offset = int(Range.removeprefix("bytes=").removesuffix("-")) if Range is not None else 0
        assert offset < len(self._objects[Key]), "Invalid range requested"

        fail_after_bytes = self._fail_first_read_after_bytes if self._get_counts[Key] == 1 else None
        return {
            "Body": FakeStreamingBody(self._objects[Key][offset:], fail_after_bytes),
            "ContentLength": len(self._objects[Key]) - offset,
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


@pytest.mark.parametrize("fail_after_bytes", [0, PRODUCER_CHUNK_SIZE])
async def test_stream_record_batches_from_s3_resumes_after_mid_file_failure(
    fail_after_bytes: int, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        producer_module,
        "make_retryable_with_exponential_backoff",
        functools.partial(make_retryable_with_exponential_backoff, initial_retry_delay=0, max_delay_jitter=0),
    )

    batches, ipc_bytes = generate_arrow_ipc_file()
    assert len(ipc_bytes) > PRODUCER_CHUNK_SIZE

    key = "batch-export-data/file_0.arrow"
    fake_s3_client = FakeS3Client({key: ipc_bytes}, fail_first_read_after_bytes=fail_after_bytes)
    queue = RecordBatchQueue()
    producer = Producer()

    s3_client = typing.cast("S3Client", fake_s3_client)
    await producer._stream_record_batches_from_s3(s3_client, [key], queue)

    consumed = []
    while not queue.empty():
        consumed.append(queue.get_nowait())

    expected_table = pa.Table.from_batches(batches)
    assert pa.Table.from_batches(consumed, schema=expected_table.schema).equals(expected_table)
    assert producer.records_produced == expected_table.num_rows

    assert len(fake_s3_client.get_object_requests) == 2
    retry_key, retry_range = fake_s3_client.get_object_requests[1]
    assert retry_key == key

    if fail_after_bytes == 0:
        # Failed before any batch was enqueued: the retry must re-read the whole file.
        assert retry_range is None
    else:
        assert retry_range is not None
        offset = int(retry_range.removeprefix("bytes=").removesuffix("-"))
        assert 0 < offset < len(ipc_bytes)
        # The resume offset must land on an IPC message boundary, past the schema message.
        assert ipc_bytes[offset : offset + 4] == asyncpa.CONTINUATION_BYTES

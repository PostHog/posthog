import io
import random
import string
import collections.abc

import pytest

import pyarrow as pa

from posthog.temporal.common import asyncpa

pytestmark = [pytest.mark.asyncio]


class AsyncWrapper:
    def __init__(self, buffer: io.BytesIO, chunk_size: int = 1024) -> None:
        self.buffer = buffer
        self.chunk_size = chunk_size

    def __aiter__(self) -> "AsyncWrapper":
        return self

    async def __anext__(self) -> bytes:
        b = self.buffer.read(self.chunk_size)

        if b == b"":
            raise StopAsyncIteration
        else:
            return b


def generate_record_batches(total_records: int = 1_000, total_batches: int = 10, target_size_bytes: int = 10 * 1024):
    """Generate record batches for testing.

    Currently, all the record batches will have the same schema: Two fields, an
    `int` id and a `str` text. The text will be random letters to fill up
    `target_size_bytes`.
    """
    records_per_batch = total_records // total_batches
    remaining_records = total_records % total_batches

    for batch_number in range(total_batches):
        batch_size = records_per_batch
        if batch_number == total_batches - 1:
            # Last batch will contain any remainder.
            batch_size += remaining_records

        records = [
            {
                "id": record_number + (batch_number * records_per_batch),
                "text": "".join(random.choices(string.ascii_letters, k=target_size_bytes)),
            }
            for record_number in range(batch_size)
        ]
        yield pa.RecordBatch.from_pylist(records)


@pytest.mark.parametrize(
    "record_batches",
    [
        iter(
            [
                pa.RecordBatch.from_arrays(
                    [
                        pa.array([2, 2, 4, 4, 5, 100]),
                        pa.array(["Flamingo", "Parrot", "Dog", "Horse", "Brittle stars", "Centipede"]),
                    ],
                    names=["n_legs", "animals"],
                )
            ]
        ),
        generate_record_batches(),
    ],
)
async def test_record_batch_reader_reads_record_batches(record_batches: collections.abc.Iterator[pa.RecordBatch]):
    """Test record batches are read correctly."""
    buffer = io.BytesIO()
    first_batch = next(record_batches)

    reader = asyncpa.AsyncRecordBatchReader(AsyncWrapper(buffer))

    # We write a record batch into a buffer, immediately read it, and compare
    # the record batch we just wrote with the one we just read.
    # This way, we avoid having to store all record batches in memory at once.
    with pa.ipc.new_stream(buffer, schema=first_batch.schema) as writer:
        writer.write_batch(first_batch)

        _ = buffer.seek(0)

        read_batch = await anext(reader)

        assert first_batch == read_batch
        assert first_batch is not read_batch

        _ = buffer.seek(0)
        _ = buffer.truncate()

        for record_batch in record_batches:
            writer.write_batch(record_batch)

            _ = buffer.seek(0)

            read_batch = await anext(reader)

            assert record_batch == read_batch
            assert record_batch is not read_batch

            _ = buffer.seek(0)
            _ = buffer.truncate()


@pytest.mark.parametrize("batches_before_resume", [1, 5, 10])
async def test_record_batch_reader_resumes_from_byte_offset(batches_before_resume: int):
    total_batches = 10
    batches = list(generate_record_batches(total_records=100, total_batches=total_batches, target_size_bytes=1024))

    buffer = io.BytesIO()
    with pa.ipc.new_stream(buffer, schema=batches[0].schema) as writer:
        for batch in batches:
            writer.write_batch(batch)
    data = buffer.getvalue()

    reader = asyncpa.AsyncRecordBatchReader(AsyncWrapper(io.BytesIO(data)))
    batches_read = [await anext(reader) for _ in range(batches_before_resume)]
    offset = reader.bytes_consumed

    assert batches_read == batches[:batches_before_resume]
    # The offset must land on an IPC message boundary (either the next record batch or the EOS marker).
    assert data[offset : offset + 4] == asyncpa.CONTINUATION_BYTES

    resumed_reader = asyncpa.AsyncRecordBatchReader(AsyncWrapper(io.BytesIO(data[offset:])), schema=reader.schema)
    batches_resumed = [batch async for batch in resumed_reader]

    assert batches_resumed == batches[batches_before_resume:]

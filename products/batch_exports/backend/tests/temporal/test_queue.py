"""Tests for the record batch queue that carries data from producer to consumer."""

import asyncio

import pytest

import pyarrow as pa

from products.batch_exports.backend.temporal.queue import RecordBatchQueue

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


async def test_record_batch_queue_tracks_bytes():
    """Test `RecordBatchQueue` tracks bytes from `RecordBatch`."""
    records = [{"test": 1}, {"test": 2}, {"test": 3}]
    record_batch = pa.RecordBatch.from_pylist(records)

    queue = RecordBatchQueue()

    await queue.put(record_batch)
    assert record_batch.get_total_buffer_size() == queue.qsize()

    item = await queue.get()

    assert item == record_batch
    assert queue.qsize() == 0


async def test_record_batch_queue_raises_queue_full():
    """Test `QueueFull` is raised when we put too many bytes."""
    records = [{"test": 1}, {"test": 2}, {"test": 3}]
    record_batch = pa.RecordBatch.from_pylist(records)
    record_batch_size = record_batch.get_total_buffer_size()

    queue = RecordBatchQueue(max_size_bytes=record_batch_size)

    await queue.put(record_batch)
    assert record_batch.get_total_buffer_size() == queue.qsize()

    with pytest.raises(asyncio.QueueFull):
        queue.put_nowait(record_batch)

    item = await queue.get()

    assert item == record_batch
    assert queue.qsize() == 0


async def test_record_batch_queue_sets_schema():
    """Test `RecordBatchQueue` sets a schema from first `RecordBatch`."""
    records = [{"test": 1}, {"test": 2}, {"test": 3}]
    record_batch = pa.RecordBatch.from_pylist(records)

    queue = RecordBatchQueue()

    await queue.put(record_batch)

    assert queue._schema_set.is_set()

    schema = await queue.get_schema()
    assert schema == record_batch.schema


async def test_record_batch_queue_str_and_repr():
    """Test `RecordBatchQueue` returns sensible output for str and repr"""
    records = [{"test": 1}, {"test": 2}, {"test": 3}]
    record_batch = pa.RecordBatch.from_pylist(records)

    queue = RecordBatchQueue()

    await queue.put(record_batch)

    assert str(queue) == "<RecordBatchQueue record_batches=1 bytes=24 schema='test: int64'>"
    assert "record_batches=1 bytes=24 schema='test: int64'" in repr(queue)

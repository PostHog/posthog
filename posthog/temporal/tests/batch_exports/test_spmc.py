import asyncio
import datetime as dt
import random

import pyarrow as pa
import pytest

from posthog.temporal.batch_exports.spmc import Producer, RecordBatchQueue
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse

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


async def get_record_batch_from_queue(queue, produce_task):
    while not queue.empty() or not produce_task.done():
        try:
            record_batch = queue.get_nowait()
        except asyncio.QueueEmpty:
            if produce_task.done():
                break
            else:
                await asyncio.sleep(0.1)
                continue

        return record_batch
    return None


async def get_all_record_batches_from_queue(queue, produce_task):
    records = []
    while not queue.empty() or not produce_task.done():
        record_batch = await get_record_batch_from_queue(queue, produce_task)
        if record_batch is None:
            break

        for record in record_batch.to_pylist():
            records.append(record)
    return records


async def test_record_batch_producer_uses_extra_query_parameters(clickhouse_client):
    """Test RecordBatch Producer uses a HogQL value."""
    team_id = random.randint(1, 1000000)
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:31:00.000000+00:00")
    data_interval_start = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    (events, _, _) = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10,
        count_outside_range=0,
        count_other_team=0,
        duplicate=False,
        properties={"$browser": "Chrome", "$os": "Mac OS X", "custom": 3},
    )

    queue = RecordBatchQueue()
    producer = Producer(clickhouse_client=clickhouse_client)
    producer_task = producer.start(
        queue=queue,
        team_id=team_id,
        is_backfill=False,
        model_name="events",
        full_range=(data_interval_start, data_interval_end),
        done_ranges=[],
        fields=[
            {"expression": "JSONExtractInt(properties, %(hogql_val_0)s)", "alias": "custom_prop"},
        ],
        extra_query_parameters={"hogql_val_0": "custom"},
    )

    records = await get_all_record_batches_from_queue(queue, producer_task)

    for expected, record in zip(events, records):
        if expected["properties"] is None:
            raise ValueError("Empty properties")

        assert record["custom_prop"] == expected["properties"]["custom"]

import asyncio
import datetime as dt
import random
import typing
from collections.abc import Collection

import pyarrow as pa
import pytest

from posthog.batch_exports.service import BackfillDetails
from posthog.hogql.hogql import ast
from posthog.temporal.batch_exports.spmc import (
    Producer,
    RecordBatchQueue,
    SessionsRecordBatchModel,
    compose_filters_clause,
    slice_record_batch,
    use_distributed_events_recent_table,
)
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
    producer = Producer()
    producer_task = await producer.start(
        queue=queue,
        team_id=team_id,
        is_backfill=False,
        backfill_details=None,
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


def test_slice_record_batch_into_single_record_slices():
    """Test we slice a record batch into slices with a single record."""
    n_legs = pa.array([2, 2, 4, 4, 5, 100])
    animals = pa.array(["Flamingo", "Parrot", "Dog", "Horse", "Brittle stars", "Centipede"])
    arrays: Collection[pa.Array[typing.Any]] = [n_legs, animals]
    batch = pa.RecordBatch.from_arrays(arrays, names=["n_legs", "animals"])

    slices = list(slice_record_batch(batch, max_record_batch_size_bytes=1, min_records_per_batch=1))
    assert len(slices) == 6
    assert all(slice.num_rows == 1 for slice in slices)


def test_slice_record_batch_into_one_batch():
    """Test we do not slice a record batch without a bytes limit."""
    n_legs = pa.array([2, 2, 4, 4, 5, 100])
    animals = pa.array(["Flamingo", "Parrot", "Dog", "Horse", "Brittle stars", "Centipede"])
    batch = pa.RecordBatch.from_arrays([n_legs, animals], names=["n_legs", "animals"])  # type: ignore

    slices = list(slice_record_batch(batch, max_record_batch_size_bytes=0))
    assert len(slices) == 1
    assert all(slice.num_rows == 6 for slice in slices)


def test_slice_record_batch_in_half():
    """Test we can slice a record batch into half size."""
    n_legs = pa.array([4] * 6)
    animals = pa.array(["Dog"] * 6)
    batch = pa.RecordBatch.from_arrays([n_legs, animals], names=["n_legs", "animals"])  # type: ignore

    slices = list(slice_record_batch(batch, max_record_batch_size_bytes=batch.nbytes // 2, min_records_per_batch=1))
    assert len(slices) == 2
    assert all(slice.num_rows == 3 for slice in slices)


def test_slice_large_record_batch():
    """Test we can slice a record batch with plenty of elements and data.

    We construct an array with a large payload and attempt to slice it evenly.
    We assert that the count of rows matches expected, all ids are accounted
    for, the number of slices matches what we expect, and that each slice
    has the same number of rows.
    """
    size = 1_000_000
    one_tenth = size / 10

    payload = pa.array([b"0" * (1024)] * size, type=pa.large_binary())
    id = pa.array(list(range(size)))
    batch = pa.RecordBatch.from_arrays([id, payload], names=["id", "payload"])  # type: ignore

    # Large binary allocates additional 8 bytes per row.
    # Id array is int64, and takes up 8 bytes per row.
    # So, we add 16 bytes per row (16 * 1000 total) to get evenly split record
    # batches of 1k rows each.
    slices = list(
        slice_record_batch(batch, max_record_batch_size_bytes=int(one_tenth * (1024 + 16)), min_records_per_batch=1)
    )
    expected_len = 10
    result_len = len(slices)
    concatenated = pa.concat_arrays(s.column("id") for s in slices)

    assert sum(slice.num_rows for slice in slices) == size
    assert concatenated.to_pylist() == list(range(size))
    assert result_len == expected_len, f"Have {result_len} slices, expected {expected_len}"
    assert all(slice.num_rows == one_tenth for slice in slices)


@pytest.mark.parametrize(
    "test_data",
    [
        # isn't a backfill so should use distributed_events_recent table
        {
            "is_backfill": False,
            "data_interval_start": dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=1),
            "use_distributed_events_recent_table": True,
        },
        # is a backfill within the last 6 days so should use distributed_events_recent table
        {
            "is_backfill": True,
            "backfill_start_at": dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=1),
            "data_interval_start": dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=1),
            "use_distributed_events_recent_table": True,
        },
        # is a backfill outside the last 6 days so shouldn't use distributed_events_recent table
        {
            "is_backfill": True,
            "backfill_start_at": dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=7),
            "data_interval_start": dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=1),
            "use_distributed_events_recent_table": False,
        },
    ],
)
def test_use_distributed_events_recent_table(test_data: dict[str, typing.Any]):
    backfill_details = (
        BackfillDetails(
            backfill_id=None,
            start_at=test_data["backfill_start_at"].isoformat(),
            end_at=(test_data["backfill_start_at"] + dt.timedelta(days=1)).isoformat(),
            is_earliest_backfill=False,
        )
        if test_data["is_backfill"]
        else None
    )
    assert (
        use_distributed_events_recent_table(
            test_data["is_backfill"], backfill_details, data_interval_start=test_data["data_interval_start"]
        )
        == test_data["use_distributed_events_recent_table"]
    )


@pytest.mark.parametrize(
    "filters,expected_clause,expected_values",
    [
        (
            [
                {"key": "$browser", "operator": "exact", "type": "event", "value": ["Firefox"]},
            ],
            """ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', ''), %(hogql_val_1)s), 0)""",
            {"hogql_val_0": "$browser", "hogql_val_1": "Firefox"},
        ),
        (
            [
                {"key": "$current_url", "operator": "icontains", "type": "event", "value": "https://posthog.com"},
            ],
            """ifNull(ilike(toString(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', '')), %(hogql_val_1)s), 0)""",
            {"hogql_val_0": "$current_url", "hogql_val_1": "%https://posthog.com%"},
        ),
        (
            [
                {"key": "$browser", "operator": "exact", "type": "event", "value": ["Firefox"]},
                {"key": "test", "operator": "exact", "type": "event", "value": ["Test"]},
            ],
            """and(ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^"|"$', ''), %(hogql_val_1)s), 0), ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_2)s), ''), 'null'), '^"|"$', ''), %(hogql_val_3)s), 0))""",
            {"hogql_val_0": "$browser", "hogql_val_1": "Firefox", "hogql_val_2": "test", "hogql_val_3": "Test"},
        ),
    ],
)
def test_compose_filters_clause(
    filters: list[dict[str, typing.Any]], expected_clause: str, expected_values: dict[str, str], ateam
):
    result_clause, result_values = compose_filters_clause(filters, team_id=ateam.id)
    assert result_clause == expected_clause
    assert result_values == expected_values


async def test_sessions_record_batch_model(ateam, data_interval_start, data_interval_end):
    model = SessionsRecordBatchModel(
        team_id=ateam.id,
    )
    hogql_query = model.get_hogql_query(data_interval_start, data_interval_end)
    team_id_filter = ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=["sessions", "team_id"]),
        right=ast.Constant(value=ateam.id),
    )
    printed_query, _ = await model.as_query_with_parameters(data_interval_start, data_interval_end)

    assert hogql_query.where is not None
    assert isinstance(hogql_query.where, ast.And)
    assert team_id_filter in hogql_query.where.exprs

    assert f"equals(raw_sessions.team_id, {ateam.id})" in printed_query
    assert "FORMAT ArrowStream" in printed_query
    assert (
        f"greaterOrEquals(_inserted_at, toDateTime64('{data_interval_start:%Y-%m-%d %H:%M:%S.%f}', 6, 'UTC')"
        in printed_query
    )
    assert f"less(_inserted_at, toDateTime64('{data_interval_end:%Y-%m-%d %H:%M:%S.%f}', 6, 'UTC')" in printed_query

    # check that we have a date range set on the inner query using the session ID
    assert (
        "lessOrEquals(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)), plus("
        in printed_query
    )
    assert (
        "greaterOrEquals(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)), minus("
        in printed_query
    )

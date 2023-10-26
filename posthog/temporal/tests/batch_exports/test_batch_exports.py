import csv
import dataclasses
import datetime as dt
import io
import json
import logging
import operator
import random
import string
import uuid
from random import randint
from typing import TypedDict
from unittest.mock import patch
from uuid import uuid4

import aiohttp
import pytest
import pytest_asyncio
from django.conf import settings
from freezegun import freeze_time
from temporalio import activity, workflow

from posthog.clickhouse.log_entries import (
    KAFKA_LOG_ENTRIES,
)
from posthog.temporal.tests.batch_exports.base import (
    to_isoformat,
)
from posthog.temporal.workflows.batch_exports import (
    BatchExportTemporaryFile,
    KafkaLoggingHandler,
    get_batch_exports_logger,
    get_data_interval,
    get_results_iterator,
    get_rows_count,
    json_dumps_bytes,
)
from posthog.temporal.workflows.clickhouse import ClickHouseClient

EventValues = TypedDict(
    "EventValues",
    {
        "uuid": str,
        "event": str,
        "_timestamp": str,
        "timestamp": str,
        "inserted_at": str,
        "created_at": str,
        "distinct_id": str,
        "person_id": str,
        "person_properties": dict | None,
        "team_id": int,
        "properties": dict | None,
        "elements_chain": str | None,
        "elements": str | None,
        "ip": str | None,
        "site_url": str | None,
        "set": str | None,
        "set_once": str | None,
    },
)


async def insert_events(ch_client: ClickHouseClient, events: list[EventValues]):
    """Insert some events into the sharded_events table."""
    await ch_client.execute_query(
        f"""
        INSERT INTO `sharded_events` (
            uuid,
            event,
            timestamp,
            _timestamp,
            inserted_at,
            person_id,
            team_id,
            properties,
            elements_chain,
            distinct_id,
            created_at,
            person_properties
        )
        VALUES
        """,
        *[
            (
                event["uuid"],
                event["event"],
                event["timestamp"],
                event["_timestamp"],
                event["inserted_at"],
                event["person_id"],
                event["team_id"],
                json.dumps(event["properties"]) if isinstance(event["properties"], dict) else event["properties"],
                event["elements_chain"],
                event["distinct_id"],
                event["created_at"],
                json.dumps(event["person_properties"])
                if isinstance(event["person_properties"], dict)
                else event["person_properties"],
            )
            for event in events
        ],
    )


@pytest_asyncio.fixture
async def client():
    async with aiohttp.ClientSession() as session:
        client = ClickHouseClient(
            session=session,
            url=settings.CLICKHOUSE_HTTP_URL,
            user=settings.CLICKHOUSE_USER,
            password=settings.CLICKHOUSE_PASSWORD,
            database=settings.CLICKHOUSE_DATABASE,
        )
        count = int(await client.read_query("SELECT count(*) FROM `sharded_events`"))

        yield client

        new_count = int(await client.read_query("SELECT count(*) FROM `sharded_events`"))
        if new_count > count:
            await client.execute_query("TRUNCATE TABLE `sharded_events`")


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_get_rows_count(client):
    """Test the count of rows returned by get_rows_count."""
    team_id = randint(1, 1000000)

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": "test",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "inserted_at": f"2023-04-20 14:30:00.{i:06d}",
            "created_at": "2023-04-20 14:30:00.000000",
            "distinct_id": str(uuid4()),
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team_id,
            "properties": {
                "$browser": "Chrome",
                "$os": "Mac OS X",
                "$ip": "127.0.0.1",
                "$current_url": "http://localhost.com",
            },
            "elements_chain": "this that and the other",
            "elements": json.dumps("this that and the other"),
            "ip": "127.0.0.1",
            "site_url": "http://localhost.com",
            "set": None,
            "set_once": None,
        }
        for i in range(10000)
    ]
    await insert_events(
        ch_client=client,
        events=events,
    )

    row_count = await get_rows_count(client, team_id, "2023-04-20 14:30:00", "2023-04-20 14:31:00")
    assert row_count == 10000


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_get_rows_count_handles_duplicates(client):
    """Test the count of rows returned by get_rows_count are de-duplicated."""
    team_id = randint(1, 1000000)

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": "test",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "inserted_at": f"2023-04-20 14:30:00.{i:06d}",
            "created_at": "2023-04-20 14:30:00.000000",
            "distinct_id": str(uuid4()),
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team_id,
            "properties": {
                "$browser": "Chrome",
                "$os": "Mac OS X",
                "$ip": "127.0.0.1",
                "$current_url": "http://localhost.com",
            },
            "elements_chain": "this that and the other",
            "elements": json.dumps("this that and the other"),
            "ip": "127.0.0.1",
            "site_url": "http://localhost.com",
            "set": None,
            "set_once": None,
        }
        for i in range(10000)
    ]
    # Duplicate everything
    duplicate_events = events * 2

    await insert_events(
        ch_client=client,
        events=duplicate_events,
    )

    row_count = await get_rows_count(client, team_id, "2023-04-20 14:30:00", "2023-04-20 14:31:00")
    assert row_count == 10000


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_get_rows_count_can_exclude_events(client):
    """Test the count of rows returned by get_rows_count can exclude events."""
    team_id = randint(1, 1000000)

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": f"test-{i}",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "inserted_at": f"2023-04-20 14:30:00.{i:06d}",
            "created_at": "2023-04-20 14:30:00.000000",
            "distinct_id": str(uuid4()),
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team_id,
            "properties": {
                "$browser": "Chrome",
                "$os": "Mac OS X",
                "$ip": "127.0.0.1",
                "$current_url": "http://localhost.com",
            },
            "elements_chain": "this that and the other",
            "elements": json.dumps("this that and the other"),
            "ip": "127.0.0.1",
            "site_url": "http://localhost.com",
            "set": None,
            "set_once": None,
        }
        for i in range(10000)
    ]
    # Duplicate everything
    duplicate_events = events * 2

    await insert_events(
        ch_client=client,
        events=duplicate_events,
    )

    # Exclude the latter half of events.
    exclude_events = (f"test-{i}" for i in range(5000, 10000))
    row_count = await get_rows_count(
        client,
        team_id,
        "2023-04-20 14:30:00",
        "2023-04-20 14:31:00",
        exclude_events=exclude_events,
    )
    assert row_count == 5000


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_get_rows_count_can_include_events(client):
    """Test the count of rows returned by get_rows_count can include events."""
    team_id = randint(1, 1000000)

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": f"test-{i}",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "inserted_at": f"2023-04-20 14:30:00.{i:06d}",
            "created_at": "2023-04-20 14:30:00.000000",
            "distinct_id": str(uuid4()),
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team_id,
            "properties": {
                "$browser": "Chrome",
                "$os": "Mac OS X",
                "$ip": "127.0.0.1",
                "$current_url": "http://localhost.com",
            },
            "elements_chain": "this that and the other",
            "elements": json.dumps("this that and the other"),
            "ip": "127.0.0.1",
            "site_url": "http://localhost.com",
            "set": None,
            "set_once": None,
        }
        for i in range(10000)
    ]
    # Duplicate everything
    duplicate_events = events * 2

    await insert_events(
        ch_client=client,
        events=duplicate_events,
    )

    # Include the latter half of events.
    include_events = (f"test-{i}" for i in range(5000, 10000))
    row_count = await get_rows_count(
        client,
        team_id,
        "2023-04-20 14:30:00",
        "2023-04-20 14:31:00",
        include_events=include_events,
    )
    assert row_count == 5000


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.parametrize("include_person_properties", (False, True))
async def test_get_results_iterator(client, include_person_properties):
    """Test the rows returned by get_results_iterator."""
    team_id = randint(1, 1000000)

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": f"test-{i}",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "inserted_at": f"2023-04-20 14:30:00.{i:06d}",
            "created_at": "2023-04-20 14:30:00.000000",
            "distinct_id": str(uuid4()),
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team_id,
            "properties": {
                "$browser": "Chrome",
                "$os": "Mac OS X",
                "$ip": "127.0.0.1",
                "$current_url": "http://localhost.com",
            },
            "elements_chain": "this that and the other",
            "elements": json.dumps("this that and the other"),
            "ip": "127.0.0.1",
            "site_url": "",
            "set": None,
            "set_once": None,
        }
        for i in range(20000)
    ]
    await insert_events(
        ch_client=client,
        events=events,
    )

    iter_ = get_results_iterator(
        client,
        team_id,
        "2023-04-20 14:30:00",
        "2023-04-20 14:31:00",
        include_person_properties=include_person_properties,
    )
    rows = [row for row in iter_]

    all_expected = sorted(events, key=operator.itemgetter("event"))
    all_result = sorted(rows, key=operator.itemgetter("event"))

    assert len(all_expected) == len(all_result)

    for expected, result in zip(all_expected, all_result):
        for key, value in result.items():
            if key == "person_properties" and not include_person_properties:
                continue

            if key in ("timestamp", "inserted_at", "created_at"):
                expected_value = to_isoformat(expected[key])
            else:
                expected_value = expected[key]

            # Some keys will be missing from result, so let's only check the ones we have.
            assert value == expected_value, f"{key} value in {result} didn't match value in {expected}"


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.parametrize("include_person_properties", (False, True))
async def test_get_results_iterator_handles_duplicates(client, include_person_properties):
    """Test the rows returned by get_results_iterator are de-duplicated."""
    team_id = randint(1, 1000000)

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": f"test-{i}",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "inserted_at": f"2023-04-20 14:30:00.{i:06d}",
            "created_at": "2023-04-20 14:30:00.000000",
            "distinct_id": str(uuid4()),
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team_id,
            "properties": {
                "$browser": "Chrome",
                "$os": "Mac OS X",
                "$ip": "127.0.0.1",
                "$current_url": "http://localhost.com",
            },
            "elements_chain": "this that and the other",
            "elements": json.dumps("this that and the other"),
            "ip": "127.0.0.1",
            "site_url": "",
            "set": None,
            "set_once": None,
        }
        for i in range(10000)
    ]
    duplicate_events = events * 2

    await insert_events(
        ch_client=client,
        events=duplicate_events,
    )

    iter_ = get_results_iterator(
        client,
        team_id,
        "2023-04-20 14:30:00",
        "2023-04-20 14:31:00",
        include_person_properties=include_person_properties,
    )
    rows = [row for row in iter_]

    all_expected = sorted(events, key=operator.itemgetter("event"))
    all_result = sorted(rows, key=operator.itemgetter("event"))

    assert len(all_expected) == len(all_result)
    assert len([row["uuid"] for row in all_result]) == len(set(row["uuid"] for row in all_result))

    for expected, result in zip(all_expected, all_result):
        for key, value in result.items():
            if key == "person_properties" and not include_person_properties:
                continue

            if key in ("timestamp", "inserted_at", "created_at"):
                expected_value = to_isoformat(expected[key])
            else:
                expected_value = expected[key]

            # Some keys will be missing from result, so let's only check the ones we have.
            assert value == expected_value, f"{key} value in {result} didn't match value in {expected}"


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.parametrize("include_person_properties", (False, True))
async def test_get_results_iterator_can_exclude_events(client, include_person_properties):
    """Test the rows returned by get_results_iterator can exclude events."""
    team_id = randint(1, 1000000)

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": f"test-{i}",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "inserted_at": f"2023-04-20 14:30:00.{i:06d}",
            "created_at": "2023-04-20 14:30:00.000000",
            "distinct_id": str(uuid4()),
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team_id,
            "properties": {
                "$browser": "Chrome",
                "$os": "Mac OS X",
                "$ip": "127.0.0.1",
                "$current_url": "http://localhost.com",
            },
            "elements_chain": "this that and the other",
            "elements": json.dumps("this that and the other"),
            "ip": "127.0.0.1",
            "site_url": "",
            "set": None,
            "set_once": None,
        }
        for i in range(10000)
    ]
    duplicate_events = events * 2

    await insert_events(
        ch_client=client,
        events=duplicate_events,
    )

    # Exclude the latter half of events.
    exclude_events = (f"test-{i}" for i in range(5000, 10000))
    iter_ = get_results_iterator(
        client,
        team_id,
        "2023-04-20 14:30:00",
        "2023-04-20 14:31:00",
        exclude_events=exclude_events,
        include_person_properties=include_person_properties,
    )
    rows = [row for row in iter_]

    all_expected = sorted(events[:5000], key=operator.itemgetter("event"))
    all_result = sorted(rows, key=operator.itemgetter("event"))

    assert len(all_expected) == len(all_result)
    assert len([row["uuid"] for row in all_result]) == len(set(row["uuid"] for row in all_result))

    for expected, result in zip(all_expected, all_result):
        for key, value in result.items():
            if key == "person_properties" and not include_person_properties:
                continue

            if key in ("timestamp", "inserted_at", "created_at"):
                expected_value = to_isoformat(expected[key])
            else:
                expected_value = expected[key]

            # Some keys will be missing from result, so let's only check the ones we have.
            assert value == expected_value, f"{key} value in {result} didn't match value in {expected}"


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.parametrize("include_person_properties", (False, True))
async def test_get_results_iterator_can_include_events(client, include_person_properties):
    """Test the rows returned by get_results_iterator can include events."""
    team_id = randint(1, 1000000)

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": f"test-{i}",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "inserted_at": f"2023-04-20 14:30:00.{i:06d}",
            "created_at": "2023-04-20 14:30:00.000000",
            "distinct_id": str(uuid4()),
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team_id,
            "properties": {
                "$browser": "Chrome",
                "$os": "Mac OS X",
                "$ip": "127.0.0.1",
                "$current_url": "http://localhost.com",
            },
            "elements_chain": "this that and the other",
            "elements": json.dumps("this that and the other"),
            "ip": "127.0.0.1",
            "site_url": "",
            "set": None,
            "set_once": None,
        }
        for i in range(10000)
    ]
    duplicate_events = events * 2

    await insert_events(
        ch_client=client,
        events=duplicate_events,
    )

    # Include the latter half of events.
    include_events = (f"test-{i}" for i in range(5000, 10000))
    iter_ = get_results_iterator(
        client,
        team_id,
        "2023-04-20 14:30:00",
        "2023-04-20 14:31:00",
        include_events=include_events,
        include_person_properties=include_person_properties,
    )
    rows = [row for row in iter_]

    all_expected = sorted(events[5000:], key=operator.itemgetter("event"))
    all_result = sorted(rows, key=operator.itemgetter("event"))

    assert len(all_expected) == len(all_result)
    assert len([row["uuid"] for row in all_result]) == len(set(row["uuid"] for row in all_result))

    for expected, result in zip(all_expected, all_result):
        for key, value in result.items():
            if key == "person_properties" and not include_person_properties:
                continue

            if key in ("timestamp", "inserted_at", "created_at"):
                expected_value = to_isoformat(expected[key])
            else:
                expected_value = expected[key]

            # Some keys will be missing from result, so let's only check the ones we have.
            assert value == expected_value, f"{key} value in {result} didn't match value in {expected}"


@pytest.mark.parametrize(
    "interval,data_interval_end,expected",
    [
        (
            "hour",
            "2023-08-01T00:00:00+00:00",
            (
                dt.datetime(2023, 7, 31, 23, 0, 0, tzinfo=dt.timezone.utc),
                dt.datetime(2023, 8, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
            ),
        ),
        (
            "day",
            "2023-08-01T00:00:00+00:00",
            (
                dt.datetime(2023, 7, 31, 0, 0, 0, tzinfo=dt.timezone.utc),
                dt.datetime(2023, 8, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
            ),
        ),
    ],
)
def test_get_data_interval(interval, data_interval_end, expected):
    """Test get_data_interval returns the expected data interval tuple."""
    result = get_data_interval(interval, data_interval_end)
    assert result == expected


@pytest.mark.parametrize(
    "to_write",
    [
        (b"",),
        (b"", b""),
        (b"12345",),
        (b"12345", b"12345"),
        (b"abbcccddddeeeee",),
        (b"abbcccddddeeeee", b"abbcccddddeeeee"),
    ],
)
def test_batch_export_temporary_file_tracks_bytes(to_write):
    """Test the bytes written by BatchExportTemporaryFile match expected."""
    with BatchExportTemporaryFile() as be_file:
        for content in to_write:
            be_file.write(content)

        assert be_file.bytes_total == sum(len(content) for content in to_write)
        assert be_file.bytes_since_last_reset == sum(len(content) for content in to_write)

        be_file.reset()

        assert be_file.bytes_total == sum(len(content) for content in to_write)
        assert be_file.bytes_since_last_reset == 0


TEST_RECORDS = [
    [],
    [
        {"id": "record-1", "property": "value", "property_int": 1},
        {"id": "record-2", "property": "another-value", "property_int": 2},
        {
            "id": "record-3",
            "property": {"id": "nested-record", "property": "nested-value"},
            "property_int": 3,
        },
    ],
]


@pytest.mark.parametrize(
    "records",
    TEST_RECORDS,
)
def test_batch_export_temporary_file_write_records_to_jsonl(records):
    """Test JSONL records written by BatchExportTemporaryFile match expected."""
    jsonl_dump = b"\n".join(map(json_dumps_bytes, records))

    with BatchExportTemporaryFile() as be_file:
        be_file.write_records_to_jsonl(records)

        assert be_file.bytes_total == len(jsonl_dump)
        assert be_file.bytes_since_last_reset == len(jsonl_dump)
        assert be_file.records_total == len(records)
        assert be_file.records_since_last_reset == len(records)

        be_file.seek(0)
        lines = be_file.readlines()
        assert len(lines) == len(records)

        for line_index, jsonl_record in enumerate(lines):
            json_loaded = json.loads(jsonl_record)
            assert json_loaded == records[line_index]

        be_file.reset()

        assert be_file.bytes_total == len(jsonl_dump)
        assert be_file.bytes_since_last_reset == 0
        assert be_file.records_total == len(records)
        assert be_file.records_since_last_reset == 0


@pytest.mark.parametrize(
    "records",
    TEST_RECORDS,
)
def test_batch_export_temporary_file_write_records_to_csv(records):
    """Test CSV written by BatchExportTemporaryFile match expected."""
    in_memory_file_obj = io.StringIO()
    writer = csv.DictWriter(
        in_memory_file_obj,
        fieldnames=records[0].keys() if len(records) > 0 else [],
        delimiter=",",
        quotechar='"',
        escapechar="\\",
        quoting=csv.QUOTE_NONE,
    )
    writer.writerows(records)

    with BatchExportTemporaryFile(mode="w+") as be_file:
        be_file.write_records_to_csv(records)

        assert be_file.bytes_total == in_memory_file_obj.tell()
        assert be_file.bytes_since_last_reset == in_memory_file_obj.tell()
        assert be_file.records_total == len(records)
        assert be_file.records_since_last_reset == len(records)

        be_file.seek(0)
        reader = csv.reader(
            be_file._file,
            delimiter=",",
            quotechar='"',
            escapechar="\\",
            quoting=csv.QUOTE_NONE,
        )

        rows = [row for row in reader]
        assert len(rows) == len(records)

        for row_index, csv_record in enumerate(rows):
            for value_index, value in enumerate(records[row_index].values()):
                # Everything returned by csv.reader is a str.
                # This means type information is lost when writing to CSV
                # but this just a limitation of the format.
                assert csv_record[value_index] == str(value)

        be_file.reset()

        assert be_file.bytes_total == in_memory_file_obj.tell()
        assert be_file.bytes_since_last_reset == 0
        assert be_file.records_total == len(records)
        assert be_file.records_since_last_reset == 0


@pytest.mark.parametrize(
    "records",
    TEST_RECORDS,
)
def test_batch_export_temporary_file_write_records_to_tsv(records):
    """Test TSV written by BatchExportTemporaryFile match expected."""
    in_memory_file_obj = io.StringIO()
    writer = csv.DictWriter(
        in_memory_file_obj,
        fieldnames=records[0].keys() if len(records) > 0 else [],
        delimiter="\t",
        quotechar='"',
        escapechar="\\",
        quoting=csv.QUOTE_NONE,
    )
    writer.writerows(records)

    with BatchExportTemporaryFile(mode="w+") as be_file:
        be_file.write_records_to_tsv(records)

        assert be_file.bytes_total == in_memory_file_obj.tell()
        assert be_file.bytes_since_last_reset == in_memory_file_obj.tell()
        assert be_file.records_total == len(records)
        assert be_file.records_since_last_reset == len(records)

        be_file.seek(0)
        reader = csv.reader(
            be_file._file,
            delimiter="\t",
            quotechar='"',
            escapechar="\\",
            quoting=csv.QUOTE_NONE,
        )

        rows = [row for row in reader]
        assert len(rows) == len(records)

        for row_index, csv_record in enumerate(rows):
            for value_index, value in enumerate(records[row_index].values()):
                # Everything returned by csv.reader is a str.
                # This means type information is lost when writing to CSV
                # but this just a limitation of the format.
                assert csv_record[value_index] == str(value)

        be_file.reset()

        assert be_file.bytes_total == in_memory_file_obj.tell()
        assert be_file.bytes_since_last_reset == 0
        assert be_file.records_total == len(records)
        assert be_file.records_since_last_reset == 0


def test_kafka_logging_handler_produces_to_kafka(caplog):
    """Test a mocked call to Kafka produce from the KafkaLoggingHandler."""
    logger_name = "test-logger"
    logger = logging.getLogger(logger_name)
    handler = KafkaLoggingHandler(topic=KAFKA_LOG_ENTRIES)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    team_id = random.randint(1, 10000)
    batch_export_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    timestamp = "2023-09-21 00:01:01.000001"

    expected_tuples = []
    expected_kafka_produce_calls_kwargs = []

    with patch("posthog.kafka_client.client._KafkaProducer.produce") as produce:
        with caplog.at_level(logging.DEBUG):
            with freeze_time(timestamp):
                for level in (10, 20, 30, 40, 50):
                    random_message = "".join(random.choice(string.ascii_letters) for _ in range(30))

                    logger.log(
                        level,
                        random_message,
                        extra={
                            "team_id": team_id,
                            "batch_export_id": batch_export_id,
                            "workflow_run_id": run_id,
                        },
                    )

                    expected_tuples.append(
                        (
                            logger_name,
                            level,
                            random_message,
                        )
                    )
                    data = {
                        "message": random_message,
                        "team_id": team_id,
                        "log_source": "batch_exports",
                        "log_source_id": batch_export_id,
                        "instance_id": run_id,
                        "timestamp": timestamp,
                        "level": logging.getLevelName(level),
                    }
                    expected_kafka_produce_calls_kwargs.append({"topic": KAFKA_LOG_ENTRIES, "data": data, "key": None})

        assert caplog.record_tuples == expected_tuples

        kafka_produce_calls_kwargs = [call.kwargs for call in produce.call_args_list]
        assert kafka_produce_calls_kwargs == expected_kafka_produce_calls_kwargs


@dataclasses.dataclass
class TestInputs:
    team_id: int
    data_interval_end: str | None = None
    interval: str = "hour"
    batch_export_id: str = ""


@dataclasses.dataclass
class TestInfo:
    workflow_id: str
    run_id: str
    workflow_run_id: str
    attempt: int


@pytest.mark.parametrize("context", [activity.__name__, workflow.__name__])
def test_batch_export_logger_adapter(context, caplog):
    """Test BatchExportLoggerAdapter sets the appropiate context variables."""
    team_id = random.randint(1, 10000)
    inputs = TestInputs(team_id=team_id)
    logger = get_batch_exports_logger(inputs=inputs)

    batch_export_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    attempt = random.randint(1, 10)
    info = TestInfo(
        workflow_id=f"{batch_export_id}-{dt.datetime.utcnow().isoformat()}",
        run_id=run_id,
        workflow_run_id=run_id,
        attempt=attempt,
    )

    with patch("posthog.kafka_client.client._KafkaProducer.produce"):
        with patch(context + ".info", return_value=info):
            for level in (10, 20, 30, 40, 50):
                logger.log(level, "test")

    records = caplog.get_records("call")
    assert all(record.team_id == team_id for record in records)
    assert all(record.batch_export_id == batch_export_id for record in records)
    assert all(record.workflow_run_id == run_id for record in records)
    assert all(record.attempt == attempt for record in records)

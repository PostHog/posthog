import csv
import datetime as dt
import io
import json
import operator
from random import randint

import pytest
from django.test import override_settings

from posthog.temporal.batch_exports.batch_exports import (
    BatchExportTemporaryFile,
    get_data_interval,
    get_results_iterator,
    get_rows_count,
    json_dumps_bytes,
)
from posthog.temporal.tests.utils.datetimes import to_isoformat
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


async def test_get_rows_count(clickhouse_client):
    """Test the count of rows returned by get_rows_count."""
    team_id = randint(1, 1000000)
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:31:00.000000+00:00")
    data_interval_start = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    _ = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10000,
        count_outside_range=0,
        count_other_team=0,
        duplicate=False,
    )

    row_count = await get_rows_count(
        clickhouse_client, team_id, data_interval_start.isoformat(), data_interval_end.isoformat()
    )
    assert row_count == 10000


async def test_get_rows_count_handles_duplicates(clickhouse_client):
    """Test the count of rows returned by get_rows_count are de-duplicated."""
    team_id = randint(1, 1000000)

    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:31:00.000000+00:00")
    data_interval_start = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    _ = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10,
        count_outside_range=0,
        count_other_team=0,
        duplicate=True,
    )

    row_count = await get_rows_count(
        clickhouse_client, team_id, data_interval_start.isoformat(), data_interval_end.isoformat()
    )
    assert row_count == 10


async def test_get_rows_count_can_exclude_events(clickhouse_client):
    """Test the count of rows returned by get_rows_count can exclude events."""
    team_id = randint(1, 1000000)

    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:31:00.000000+00:00")
    data_interval_start = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    (events, _, _) = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10000,
        count_outside_range=0,
        count_other_team=0,
        duplicate=False,
    )

    # Exclude the latter half of events.
    exclude_events = (event["event"] for event in events[5000:])
    row_count = await get_rows_count(
        clickhouse_client,
        team_id,
        data_interval_start.isoformat(),
        data_interval_end.isoformat(),
        exclude_events=exclude_events,
    )
    assert row_count == 5000


async def test_get_rows_count_can_include_events(clickhouse_client):
    """Test the count of rows returned by get_rows_count can include events."""
    team_id = randint(1, 1000000)

    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:31:00.000000+00:00")
    data_interval_start = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    (events, _, _) = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=5000,
        count_outside_range=0,
        count_other_team=0,
        duplicate=False,
    )

    # Include the latter half of events.
    include_events = (event["event"] for event in events[2500:])
    row_count = await get_rows_count(
        clickhouse_client,
        team_id,
        data_interval_start.isoformat(),
        data_interval_end.isoformat(),
        include_events=include_events,
    )
    assert row_count == 2500


async def test_get_rows_count_ignores_timestamp_predicates(clickhouse_client):
    """Test the count of rows returned by get_rows_count can ignore timestamp predicates."""
    team_id = randint(1, 1000000)

    inserted_at = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")
    data_interval_end = inserted_at + dt.timedelta(hours=1)

    # Insert some data with timestamps a couple of years before inserted_at
    timestamp_start = inserted_at - dt.timedelta(hours=24 * 365 * 2)
    timestamp_end = inserted_at - dt.timedelta(hours=24 * 365)

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=timestamp_start,
        end_time=timestamp_end,
        count=10,
        count_outside_range=0,
        count_other_team=0,
        duplicate=False,
        inserted_at=inserted_at,
    )

    row_count = await get_rows_count(
        clickhouse_client,
        team_id,
        inserted_at.isoformat(),
        data_interval_end.isoformat(),
    )
    # All events are outside timestamp bounds (a year difference with inserted_at)
    assert row_count == 0

    with override_settings(UNCONSTRAINED_TIMESTAMP_TEAM_IDS=[str(team_id)]):
        row_count = await get_rows_count(
            clickhouse_client,
            team_id,
            inserted_at.isoformat(),
            data_interval_end.isoformat(),
        )
    assert row_count == 10


@pytest.mark.parametrize("include_person_properties", (False, True))
async def test_get_results_iterator(clickhouse_client, include_person_properties):
    """Test the rows returned by get_results_iterator."""
    team_id = randint(1, 1000000)
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:31:00.000000+00:00")
    data_interval_start = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    (events, _, _) = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=100,
        count_outside_range=0,
        count_other_team=0,
        duplicate=False,
        person_properties={"$browser": "Chrome", "$os": "Mac OS X"},
    )

    iter_ = get_results_iterator(
        clickhouse_client,
        team_id,
        data_interval_start.isoformat(),
        data_interval_end.isoformat(),
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


@pytest.mark.parametrize("include_person_properties", (False, True))
async def test_get_results_iterator_handles_duplicates(clickhouse_client, include_person_properties):
    """Test the rows returned by get_results_iterator are de-duplicated."""
    team_id = randint(1, 1000000)
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:31:00.000000+00:00")
    data_interval_start = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    (events, _, _) = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=100,
        count_outside_range=0,
        count_other_team=0,
        duplicate=True,
        person_properties={"$browser": "Chrome", "$os": "Mac OS X"},
    )

    iter_ = get_results_iterator(
        clickhouse_client,
        team_id,
        data_interval_start.isoformat(),
        data_interval_end.isoformat(),
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


@pytest.mark.parametrize("include_person_properties", (False, True))
async def test_get_results_iterator_can_exclude_events(clickhouse_client, include_person_properties):
    """Test the rows returned by get_results_iterator can exclude events."""
    team_id = randint(1, 1000000)
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:31:00.000000+00:00")
    data_interval_start = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    (events, _, _) = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10000,
        count_outside_range=0,
        count_other_team=0,
        duplicate=True,
        person_properties={"$browser": "Chrome", "$os": "Mac OS X"},
    )

    # Exclude the latter half of events.
    exclude_events = (event["event"] for event in events[5000:])
    iter_ = get_results_iterator(
        clickhouse_client,
        team_id,
        data_interval_start.isoformat(),
        data_interval_end.isoformat(),
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


@pytest.mark.parametrize("include_person_properties", (False, True))
async def test_get_results_iterator_can_include_events(clickhouse_client, include_person_properties):
    """Test the rows returned by get_results_iterator can include events."""
    team_id = randint(1, 1000000)
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:31:00.000000+00:00")
    data_interval_start = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    (events, _, _) = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10000,
        count_outside_range=0,
        count_other_team=0,
        duplicate=True,
        person_properties={"$browser": "Chrome", "$os": "Mac OS X"},
    )

    # Include the latter half of events.
    include_events = (event["event"] for event in events[5000:])
    iter_ = get_results_iterator(
        clickhouse_client,
        team_id,
        data_interval_start.isoformat(),
        data_interval_end.isoformat(),
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


@pytest.mark.parametrize("include_person_properties", (False, True))
async def test_get_results_iterator_ignores_timestamp_predicates(clickhouse_client, include_person_properties):
    """Test the rows returned by get_results_iterator ignores timestamp predicates when configured."""
    team_id = randint(1, 1000000)

    inserted_at = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")
    data_interval_end = inserted_at + dt.timedelta(hours=1)

    # Insert some data with timestamps a couple of years before inserted_at
    timestamp_start = inserted_at - dt.timedelta(hours=24 * 365 * 2)
    timestamp_end = inserted_at - dt.timedelta(hours=24 * 365)

    (events, _, _) = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=timestamp_start,
        end_time=timestamp_end,
        count=10,
        count_outside_range=0,
        count_other_team=0,
        duplicate=True,
        person_properties={"$browser": "Chrome", "$os": "Mac OS X"},
        inserted_at=inserted_at,
    )

    iter_ = get_results_iterator(
        clickhouse_client,
        team_id,
        inserted_at.isoformat(),
        data_interval_end.isoformat(),
        include_person_properties=include_person_properties,
    )
    rows = [row for row in iter_]

    assert len(rows) == 0

    with override_settings(UNCONSTRAINED_TIMESTAMP_TEAM_IDS=[str(team_id)]):
        iter_ = get_results_iterator(
            clickhouse_client,
            team_id,
            inserted_at.isoformat(),
            data_interval_end.isoformat(),
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

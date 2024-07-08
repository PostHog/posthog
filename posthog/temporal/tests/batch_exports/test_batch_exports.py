import datetime as dt
import json
import operator
from random import randint

import pytest
from django.test import override_settings

from posthog.batch_exports.service import BatchExportModel
from posthog.temporal.batch_exports.batch_exports import (
    get_data_interval,
    iter_model_records,
    iter_records,
)
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


def assert_records_match_events(records, events):
    """Compare records returned from ClickHouse to events inserted into ClickHouse.

    Naturally, they should match, but with some transformations:
    * We set UTC as a timezone for dates.
    * We dump dict fields
    """
    all_expected = sorted(events, key=operator.itemgetter("event"))
    all_record = sorted(records, key=operator.itemgetter("event"))

    assert len(all_expected) == len(all_record)
    assert len([record["uuid"] for record in all_record]) == len(
        {record["uuid"] for record in all_record}
    ), "duplicate records found"

    for expected, record in zip(all_expected, all_record):
        for key, value in record.items():
            value = value or None

            msg = f"{key} value in {record} didn't match value in {expected}"
            if (
                key in ("timestamp", "_inserted_at", "created_at")
                and expected.get(key.removeprefix("_"), None) is not None
            ):
                assert value == dt.datetime.fromisoformat(expected[key.removeprefix("_")]).replace(tzinfo=dt.UTC), msg
            elif isinstance(expected[key], dict):
                assert value == json.dumps(expected[key]), msg
            else:
                assert value == expected[key]


async def test_iter_records(clickhouse_client):
    """Test the rows returned by iter_records."""
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

    records = [
        record
        for record_batch in iter_records(
            clickhouse_client,
            team_id,
            data_interval_start.isoformat(),
            data_interval_end.isoformat(),
        )
        for record in record_batch.to_pylist()
    ]

    assert_records_match_events(records, events)


async def test_iter_records_handles_duplicates(clickhouse_client):
    """Test the rows returned by iter_records are de-duplicated."""
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

    records = [
        record
        for record_batch in iter_records(
            clickhouse_client,
            team_id,
            data_interval_start.isoformat(),
            data_interval_end.isoformat(),
        )
        for record in record_batch.to_pylist()
    ]

    assert_records_match_events(records, events)


async def test_iter_records_can_exclude_events(clickhouse_client):
    """Test the rows returned by iter_records can exclude events."""
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
    records = [
        record
        for record_batch in iter_records(
            clickhouse_client,
            team_id,
            data_interval_start.isoformat(),
            data_interval_end.isoformat(),
            exclude_events=exclude_events,
        )
        for record in record_batch.to_pylist()
    ]

    assert_records_match_events(records, events[:5000])


async def test_iter_records_can_include_events(clickhouse_client):
    """Test the rows returned by iter_records can include events."""
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
    records = [
        record
        for record_batch in iter_records(
            clickhouse_client,
            team_id,
            data_interval_start.isoformat(),
            data_interval_end.isoformat(),
            include_events=include_events,
        )
        for record in record_batch.to_pylist()
    ]

    assert_records_match_events(records, events[5000:])


async def test_iter_records_ignores_timestamp_predicates(clickhouse_client):
    """Test the rows returned by iter_records ignores timestamp predicates when configured."""
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

    records = [
        record
        for record_batch in iter_records(
            clickhouse_client,
            team_id,
            inserted_at.isoformat(),
            data_interval_end.isoformat(),
        )
        for record in record_batch.to_pylist()
    ]

    assert len(records) == 0

    with override_settings(UNCONSTRAINED_TIMESTAMP_TEAM_IDS=[str(team_id)]):
        records = [
            record
            for record_batch in iter_records(
                clickhouse_client,
                team_id,
                inserted_at.isoformat(),
                data_interval_end.isoformat(),
            )
            for record in record_batch.to_pylist()
        ]

    assert_records_match_events(records, events)


@pytest.mark.parametrize(
    "field",
    [
        {"expression": "event", "alias": "event_name"},
        {"expression": "team_id", "alias": "team"},
        {"expression": "timestamp", "alias": "time_the_stamp"},
        {"expression": "created_at", "alias": "creation_time"},
    ],
)
async def test_iter_records_with_single_field_and_alias(clickhouse_client, field):
    """Test iter_records can return a single aliased field."""
    team_id = randint(1, 1000000)
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
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
    )

    records = [
        record
        async for record_batch in iter_model_records(
            client=clickhouse_client,
            model=BatchExportModel(name="events", schema={"fields": [field], "values": {}}),
            team_id=team_id,
            is_backfill=False,
            interval_start=data_interval_start.isoformat(),
            interval_end=data_interval_end.isoformat(),
        )
        for record in record_batch.to_pylist()
    ]

    all_expected = sorted(events, key=operator.itemgetter(field["expression"]))
    all_record = sorted(records, key=operator.itemgetter(field["alias"]))

    for expected, record in zip(all_expected, all_record):
        assert len(record) == 2
        # Always set for progress tracking
        assert record.get("_inserted_at", None) is not None

        result = record[field["alias"]]
        expected_value = expected[field["expression"]]

        if isinstance(result, dt.datetime):
            # Event generation function returns datetimes as strings.
            expected_value = dt.datetime.fromisoformat(expected_value).replace(tzinfo=dt.UTC)

        assert result == expected_value


async def test_iter_records_can_flatten_properties(clickhouse_client):
    """Test iter_records can flatten properties as indicated by a field expression."""
    team_id = randint(1, 1000000)
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
        properties={"$browser": "Chrome", "$os": "Mac OS X", "custom-property": 3},
    )

    records = [
        record
        for record_batch in iter_records(
            clickhouse_client,
            team_id,
            data_interval_start.isoformat(),
            data_interval_end.isoformat(),
            fields=[
                {"expression": "event", "alias": "event"},
                {"expression": "JSONExtractString(properties, '$browser')", "alias": "browser"},
                {"expression": "JSONExtractString(properties, '$os')", "alias": "os"},
                {"expression": "JSONExtractInt(properties, 'custom-property')", "alias": "custom_prop"},
            ],
        )
        for record in record_batch.to_pylist()
    ]

    all_expected = sorted(events, key=operator.itemgetter("event"))
    all_record = sorted(records, key=operator.itemgetter("event"))

    for expected, record in zip(all_expected, all_record):
        if expected["properties"] is None:
            raise ValueError("Empty properties")

        assert record["browser"] == expected["properties"]["$browser"]
        assert record["os"] == expected["properties"]["$os"]
        assert record["custom_prop"] == expected["properties"]["custom-property"]


async def test_iter_records_uses_extra_query_parameters(clickhouse_client):
    """Test iter_records can flatten properties as indicated by a field expression."""
    team_id = randint(1, 1000000)
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

    records = [
        record
        for record_batch in iter_records(
            clickhouse_client,
            team_id,
            data_interval_start.isoformat(),
            data_interval_end.isoformat(),
            fields=[
                {"expression": "JSONExtractInt(properties, %(hogql_val_0)s)", "alias": "custom_prop"},
            ],
            extra_query_parameters={"hogql_val_0": "custom"},
        )
        for record in record_batch.to_pylist()
    ]

    for expected, record in zip(events, records):
        if expected["properties"] is None:
            raise ValueError("Empty properties")

        assert record["custom_prop"] == expected["properties"]["custom"]


@pytest.mark.parametrize(
    "interval,data_interval_end,expected",
    [
        (
            "hour",
            "2023-08-01T00:00:00+00:00",
            (
                dt.datetime(2023, 7, 31, 23, 0, 0, tzinfo=dt.UTC),
                dt.datetime(2023, 8, 1, 0, 0, 0, tzinfo=dt.UTC),
            ),
        ),
        (
            "day",
            "2023-08-01T00:00:00+00:00",
            (
                dt.datetime(2023, 7, 31, 0, 0, 0, tzinfo=dt.UTC),
                dt.datetime(2023, 8, 1, 0, 0, 0, tzinfo=dt.UTC),
            ),
        ),
    ],
)
def test_get_data_interval(interval, data_interval_end, expected):
    """Test get_data_interval returns the expected data interval tuple."""
    result = get_data_interval(interval, data_interval_end)
    assert result == expected

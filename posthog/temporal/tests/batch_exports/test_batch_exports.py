import json
import operator
from random import randint
from typing import TypedDict
from uuid import uuid4

import pytest
from aiochclient import ChClient
from django.conf import settings

from posthog.temporal.workflows.batch_exports import (
    get_results_iterator,
    get_rows_count,
)

EventValues = TypedDict(
    "EventValues",
    {
        "uuid": str,
        "event": str,
        "_timestamp": str,
        "timestamp": str,
        "created_at": str,
        "distinct_id": str,
        "person_id": str,
        "person_properties": dict | None,
        "team_id": int,
        "properties": dict | None,
        "elements_chain": str,
    },
)


async def insert_events(client: ChClient, events: list[EventValues]):
    """Insert some events into the sharded_events table."""
    await client.execute(
        f"""
        INSERT INTO `sharded_events` (
            uuid,
            event,
            timestamp,
            _timestamp,
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
        json=False,
    )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_get_rows_count():
    """Test the count of rows returned by get_rows_count."""
    team_id = randint(1, 1000000)

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": "test",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "created_at": "2023-04-20 14:30:00.000000",
            "distinct_id": str(uuid4()),
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team_id,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "elements_chain": "this that and the other",
        }
        # NOTE: we have to do a lot here, otherwise we do not trigger a
        # multipart upload, and the minimum part chunk size is 5MB.
        for i in range(10000)
    ]
    client = ChClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )
    await insert_events(
        client=client,
        events=events,
    )

    row_count = await get_rows_count(client, team_id, "2023-04-20 14:30:00", "2023-04-20 14:31:00")
    assert row_count == 10000


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_get_rows_count_handles_duplicates():
    """Test the count of rows returned by get_rows_count are de-duplicated."""
    team_id = randint(1, 1000000)

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": "test",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "created_at": "2023-04-20 14:30:00.000000",
            "distinct_id": str(uuid4()),
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team_id,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "elements_chain": "this that and the other",
        }
        # NOTE: we have to do a lot here, otherwise we do not trigger a
        # multipart upload, and the minimum part chunk size is 5MB.
        for i in range(10000)
    ]
    # Duplicate everything
    events = events * 2

    client = ChClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )
    await insert_events(
        client=client,
        events=events,
    )

    row_count = await get_rows_count(client, team_id, "2023-04-20 14:30:00", "2023-04-20 14:31:00")
    assert row_count == 10000


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_get_results_iterator():
    """Test the rows returned by get_results_iterator."""
    team_id = randint(1, 1000000)

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": f"test-{i}",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "created_at": "2023-04-20 14:30:00.000000",
            "distinct_id": str(uuid4()),
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team_id,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "elements_chain": "this that and the other",
        }
        for i in range(10000)
    ]
    client = ChClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )
    await insert_events(
        client=client,
        events=events,
    )

    aiter = get_results_iterator(client, team_id, "2023-04-20 14:30:00", "2023-04-20 14:31:00")
    rows = [row async for row in aiter]

    all_expected = sorted(events, key=operator.itemgetter("event"))
    all_result = sorted(rows, key=operator.itemgetter("event"))

    assert len(all_expected) == len(all_result)

    for expected, result in zip(all_expected, all_result):
        for key, value in result.items():
            # Some keys will be missing from result, so let's only check the ones we have.
            assert value == expected[key], f"{key} value in {result} didn't match value in {expected}"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_get_results_iterator_handles_duplicates():
    """Test the rows returned by get_results_iterator are de-duplicated."""
    team_id = randint(1, 1000000)

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": f"test-{i}",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "created_at": "2023-04-20 14:30:00.000000",
            "distinct_id": str(uuid4()),
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team_id,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "elements_chain": "this that and the other",
        }
        for i in range(10000)
    ]
    duplicate_events = events * 2

    client = ChClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )
    await insert_events(
        client=client,
        events=duplicate_events,
    )

    aiter = get_results_iterator(client, team_id, "2023-04-20 14:30:00", "2023-04-20 14:31:00")
    rows = [row async for row in aiter]

    all_expected = sorted(events, key=operator.itemgetter("event"))
    all_result = sorted(rows, key=operator.itemgetter("event"))

    assert len(all_expected) == len(all_result)
    assert len([row["uuid"] for row in all_result]) == len(set(row["uuid"] for row in all_result))

    for expected, result in zip(all_expected, all_result):
        for key, value in result.items():
            # Some keys will be missing from result, so let's only check the ones we have.
            assert value == expected[key], f"{key} value in {result} didn't match value in {expected}"

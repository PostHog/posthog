"""Test utilities that deal with test event generation."""

import datetime as dt
import json
import random
import typing
import uuid

from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.tests.utils.datetimes import date_range


class EventValues(typing.TypedDict):
    """Events to be inserted for testing."""

    _timestamp: str
    created_at: str
    distinct_id: str
    elements: str | None
    elements_chain: str | None
    event: str
    inserted_at: str | None
    person_id: str
    person_properties: dict | None
    properties: dict | None
    team_id: int
    timestamp: str
    uuid: str
    ip: str | None
    site_url: str | None
    set: dict | None
    set_once: dict | None


def generate_test_events(
    count: int,
    team_id: int,
    possible_datetimes: list[dt.datetime],
    event_name: str,
    inserted_at: str | dt.datetime | None = "random",
    properties: dict | None = None,
    person_properties: dict | None = None,
    ip: str | None = None,
    site_url: str | None = "",
    set_field: dict | None = None,
    set_once: dict | None = None,
    start: int = 0,
    distinct_ids: list[str] | None = None,
):
    """Generate a list of events for testing."""
    _timestamp = random.choice(possible_datetimes)

    if inserted_at == "_timestamp":
        inserted_at_value = _timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
    elif inserted_at == "random":
        inserted_at_value = random.choice(possible_datetimes).strftime("%Y-%m-%d %H:%M:%S.%f")
    elif inserted_at is None:
        inserted_at_value = None
    else:
        if not isinstance(inserted_at, dt.datetime):
            raise ValueError(f"Unsupported value for inserted_at: '{inserted_at}'")
        inserted_at_value = inserted_at.strftime("%Y-%m-%d %H:%M:%S.%f")

    events: list[EventValues] = [
        {
            "_timestamp": _timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "created_at": random.choice(possible_datetimes).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "distinct_id": random.choice(distinct_ids) if distinct_ids else str(uuid.uuid4()),
            "elements": json.dumps("css selectors;"),
            "elements_chain": "css selectors;",
            "event": event_name.format(i=i),
            "inserted_at": inserted_at_value,
            "person_id": str(uuid.uuid4()),
            "person_properties": person_properties,
            "properties": properties,
            "team_id": team_id,
            "timestamp": random.choice(possible_datetimes).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "uuid": str(uuid.uuid4()),
            "ip": ip,
            "site_url": site_url,
            "set": set_field,
            "set_once": set_once,
        }
        for i in range(start, count + start)
    ]

    return events


async def insert_event_values_in_clickhouse(client: ClickHouseClient, events: list[EventValues]):
    """Execute an insert query to insert provided EventValues into sharded_events."""
    await client.execute_query(
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
            inserted_at,
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
                event["inserted_at"],
                event["created_at"],
                json.dumps(event["person_properties"])
                if isinstance(event["person_properties"], dict)
                else event["person_properties"],
            )
            for event in events
        ],
    )


async def generate_test_events_in_clickhouse(
    client: ClickHouseClient,
    team_id: int,
    start_time: dt.datetime,
    end_time: dt.datetime,
    count: int = 100,
    count_outside_range: int = 10,
    count_other_team: int = 10,
    event_name: str = "test-{i}",
    properties: dict | None = None,
    person_properties: dict | None = None,
    inserted_at: str | dt.datetime | None = "_timestamp",
    distinct_ids: list[str] | None = None,
    duplicate: bool = False,
    batch_size: int = 10000,
) -> tuple[list[EventValues], list[EventValues], list[EventValues]]:
    """Insert test events into the sharded_events table.

    These events are used in most batch exports tests, so we have a function here to generate
    multiple events with different characteristics.

    Args:
        client: A ClickHouseClient to insert events in ClickHouse.
        team_id: The ID of the team assigned to the generated events.
        start_time: The start of the date range for datetime event fields (like inserted_at).
            This should match the start of the batch export.
        end_time: The end of the date range for datetime event fields (like inserted_at).
            This should match the end of the batch export.
        count: Number of events to generate.
        count_outside_range: Number of events to generate for the same team_id but outside the
            provided date range given by start_time and end_time.
        count_other_team: Number of events to generate in the same date range but with a different
            team_id to the one provided.
        event_name: A string to name events. This will be formatted with the event number using the 'i'
            key. If the key is ommitted from the event name then all events will have the same event name.
        properties: A properties dictionary for events.
        person_properties: A person_properties for events.
        duplicate: Generate and insert duplicate events.
    """
    possible_datetimes = list(date_range(start_time, end_time, dt.timedelta(minutes=1)))

    # Base events
    events: list[EventValues] = []
    while len(events) < count:
        events_to_insert = generate_test_events(
            count=min(count - len(events), batch_size),
            team_id=team_id,
            possible_datetimes=possible_datetimes,
            event_name=event_name,
            properties=properties,
            person_properties=person_properties,
            inserted_at=inserted_at,
            start=len(events),
            distinct_ids=distinct_ids,
        )

        # Add duplicates if required
        duplicate_events = []
        if duplicate is True:
            duplicate_events = events_to_insert

        await insert_event_values_in_clickhouse(client=client, events=events_to_insert + duplicate_events)

        events.extend(events_to_insert)

    # Events outside original date range
    delta = end_time - start_time
    possible_datetimes_outside_range = list(
        date_range(end_time + dt.timedelta(seconds=1), end_time + delta, dt.timedelta(minutes=1))
    ) + list(date_range(start_time - dt.timedelta(seconds=1), start_time - delta, dt.timedelta(minutes=1)))

    events_outside_range = generate_test_events(
        count=count_outside_range,
        team_id=team_id,
        possible_datetimes=possible_datetimes_outside_range,
        event_name=event_name,
        properties=properties,
        person_properties=person_properties,
        inserted_at=inserted_at,
        distinct_ids=distinct_ids,
    )

    # Events generated for a different team
    events_from_other_team = generate_test_events(
        count=count_other_team,
        team_id=team_id + random.randint(1, 1000),
        possible_datetimes=possible_datetimes,
        event_name=event_name,
        properties=properties,
        person_properties=person_properties,
        inserted_at=inserted_at,
        distinct_ids=distinct_ids,
    )

    await insert_event_values_in_clickhouse(client=client, events=events_outside_range + events_from_other_team)
    return (events, events_outside_range, events_from_other_team)

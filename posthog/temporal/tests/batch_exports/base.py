import datetime as dt
import json
import random
import typing
import uuid

from asgiref.sync import sync_to_async
from temporalio.client import Client

from ee.clickhouse.materialized_columns.columns import materialize
from posthog.batch_exports.models import (
    BatchExport,
    BatchExportDestination,
    BatchExportRun,
)
from posthog.batch_exports.service import sync_batch_export
from posthog.temporal.workflows.clickhouse import ClickHouseClient


class EventValues(typing.TypedDict):
    """Events to be inserted for testing."""

    _timestamp: str
    created_at: str
    distinct_id: str
    elements_chain: str | None
    event: str
    inserted_at: str
    person_id: str
    person_properties: dict | None
    properties: dict | None
    team_id: int
    timestamp: str
    uuid: str


def date_range(start: dt.datetime, stop: dt.datetime, step: dt.timedelta):
    """Generate a range of dates between two dates."""
    current = start

    while current < stop:
        yield current
        current += step


async def insert_events(
    client: ClickHouseClient,
    team,
    start_time,
    end_time,
    n: int = 100,
    n_outside_range: int = 10,
    n_other_team: int = 10,
    override_values: dict | None = None,
    duplicate: bool = False,
) -> tuple[list[EventValues], list[EventValues], list[EventValues]]:
    """Insert some events into the sharded_events table."""
    possible_datetimes = list(date_range(start_time, end_time, dt.timedelta(minutes=1)))
    if override_values is None:
        override_dict = {}
    else:
        override_dict = override_values

    properties = {"$browser": "Chrome", "$os": "Mac OS X", "super-property": "super-value"}

    events: list[EventValues] = [
        {
            "uuid": str(uuid.uuid4()),
            "event": f"test-{i}",
            "timestamp": random.choice(possible_datetimes).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "created_at": random.choice(possible_datetimes).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "inserted_at": override_dict.get(
                "inserted_at", random.choice(possible_datetimes).strftime("%Y-%m-%d %H:%M:%S.%f")
            ),
            "_timestamp": random.choice(possible_datetimes).strftime("%Y-%m-%d %H:%M:%S"),
            "person_id": str(uuid.uuid4()),
            "person_properties": override_dict.get("properties", properties),
            "team_id": team.pk,
            "properties": override_dict.get("properties", properties),
            "distinct_id": str(uuid.uuid4()),
            "elements_chain": "this is a comman, separated, list, of css selectors(?)",
        }
        for i in range(n)
    ]

    duplicate_events = []
    if duplicate is True:
        duplicate_events = events

    delta = (end_time - start_time) + dt.timedelta(hours=1)
    events_outside_range: list[EventValues] = [
        {
            "uuid": str(uuid.uuid4()),
            "event": f"test-{i}",
            "timestamp": (random.choice(possible_datetimes) + delta).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "created_at": (random.choice(possible_datetimes) + delta).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "inserted_at": override_dict.get(
                "inserted_at", (random.choice(possible_datetimes) + delta).strftime("%Y-%m-%d %H:%M:%S.%f")
            ),
            "_timestamp": (random.choice(possible_datetimes) + delta).strftime("%Y-%m-%d %H:%M:%S"),
            "person_id": str(uuid.uuid4()),
            "person_properties": override_dict.get("properties", properties),
            "team_id": team.pk,
            "properties": override_dict.get("properties", properties),
            "distinct_id": str(uuid.uuid4()),
            "elements_chain": "this is a comman, separated, list, of css selectors(?)",
        }
        for i in range(n_outside_range)
    ]

    events_from_other_team: list[EventValues] = [
        {
            "uuid": str(uuid.uuid4()),
            "event": f"test-{i}",
            "timestamp": random.choice(possible_datetimes).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "created_at": random.choice(possible_datetimes).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "inserted_at": override_dict.get(
                "inserted_at", random.choice(possible_datetimes).strftime("%Y-%m-%d %H:%M:%S.%f")
            ),
            "_timestamp": random.choice(possible_datetimes).strftime("%Y-%m-%d %H:%M:%S"),
            "person_id": str(uuid.uuid4()),
            "person_properties": override_dict.get("properties", properties),
            "team_id": team.pk + 1,
            "properties": override_dict.get("properties", properties),
            "distinct_id": str(uuid.uuid4()),
            "elements_chain": "this is a comman, separated, list, of css selectors(?)",
        }
        for i in range(n_other_team)
    ]

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
            for event in events + events_outside_range + events_from_other_team + duplicate_events
        ],
    )

    return (events, events_outside_range, events_from_other_team)


@sync_to_async
def amaterialize(table: typing.Literal["events", "person", "groups"], column: str):
    """Materialize a column in a table."""
    return materialize(table, column)


def to_isoformat(d: str | None) -> str | None:
    """Parse a string and return it as default isoformatted."""
    if d is None:
        return None
    return dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).isoformat()


def create_batch_export(team_id: int, interval: str, name: str, destination_data: dict) -> BatchExport:
    """Create a BatchExport and its underlying Schedule."""

    destination = BatchExportDestination(**destination_data)
    batch_export = BatchExport(team_id=team_id, destination=destination, interval=interval, name=name)

    sync_batch_export(batch_export, created=True)

    destination.save()
    batch_export.save()

    return batch_export


async def acreate_batch_export(team_id: int, interval: str, name: str, destination_data: dict) -> BatchExport:
    """Create a BatchExport and its underlying Schedule."""
    return await sync_to_async(create_batch_export)(team_id, interval, name, destination_data)  # type: ignore


def fetch_batch_export_runs(batch_export_id: uuid.UUID, limit: int = 100) -> list[BatchExportRun]:
    """Fetch the BatchExportRuns for a given BatchExport."""
    return list(BatchExportRun.objects.filter(batch_export_id=batch_export_id).order_by("-created_at")[:limit])


async def afetch_batch_export_runs(batch_export_id: uuid.UUID, limit: int = 100) -> list[BatchExportRun]:
    """Fetch the BatchExportRuns for a given BatchExport."""
    return await sync_to_async(fetch_batch_export_runs)(batch_export_id, limit)  # type: ignore


async def adelete_batch_export(batch_export: BatchExport, temporal: Client) -> None:
    """Delete a BatchExport and its underlying Schedule."""
    handle = temporal.get_schedule_handle(str(batch_export.id))
    await handle.delete()

    await sync_to_async(batch_export.delete)()  # type: ignore

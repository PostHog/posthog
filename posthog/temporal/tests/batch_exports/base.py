import datetime as dt
import json
import typing

from asgiref.sync import sync_to_async

from ee.clickhouse.materialized_columns.columns import materialize
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


async def insert_events(client: ClickHouseClient, events: list[EventValues]):
    """Insert some events into the sharded_events table."""

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


@sync_to_async
def amaterialize(table: typing.Literal["events", "person", "groups"], column: str):
    """Materialize a column in a table."""
    return materialize(table, column)


def to_isoformat(d: str | None) -> str | None:
    """Parse a string and return it as default isoformatted."""
    if d is None:
        return None
    return dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).isoformat()

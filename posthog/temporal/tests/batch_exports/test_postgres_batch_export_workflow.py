import datetime as dt
from random import randint
from uuid import uuid4

import psycopg2
import pytest
from django.conf import settings
from django.test import override_settings
from psycopg2 import sql

from posthog.temporal.tests.batch_exports.base import (
    EventValues,
    amaterialize,
    insert_events,
)
from posthog.temporal.workflows.batch_exports import elements_chain_to_elements
from posthog.temporal.workflows.clickhouse import ClickHouseClient
from posthog.temporal.workflows.postgres_batch_export import (
    PostgresBatchExportInputs,
    PostgresBatchExportWorkflow,
    PostgresInsertInputs,
    insert_into_postgres_activity,
)


def assert_events_in_postgres(connection, schema, table_name, events):
    """Assert provided events written to JSON in key_prefix in S3 bucket_name."""

    inserted_events = []

    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("SELECT * FROM {} ORDER BY timestamp").format(sql.Identifier(schema, table_name)))
        columns = [column.name for column in cursor.description]

        for row in cursor.fetchall():
            event = dict(zip(columns, row))
            event["timestamp"] = dt.datetime.fromisoformat(event["timestamp"].isoformat())
            inserted_events.append(event)

    expected_events = []
    for event in events:
        properties = event.get("properties", None)
        elements_chain = event.get("elements_chain", None)
        expected_event = {
            "distinct_id": event.get("distinct_id"),
            "elements": elements_chain_to_elements(elements_chain) if elements_chain else [],
            "event": event.get("event"),
            "ip": properties.get("$ip", None) if properties else None,
            "properties": event.get("properties"),
            "set": properties.get("$set", None) if properties else None,
            "set_once": properties.get("$set_once", None) if properties else None,
            "site_url": properties.get("$current_url", None) if properties else None,
            # For compatibility with CH which doesn't parse timezone component, so we add it here assuming UTC.
            "timestamp": dt.datetime.fromisoformat(event.get("timestamp") + "+00:00"),
            "team_id": event.get("team_id"),
            "uuid": event.get("uuid"),
        }
        expected_events.append(expected_event)

    expected_events.sort(key=lambda x: x["timestamp"])

    assert len(inserted_events) == len(expected_events)
    # First check one event, the first one, so that we can get a nice diff if
    # the included data is different.
    assert inserted_events[0] == expected_events[0]
    assert inserted_events == expected_events


@pytest.fixture
def postgres_config():
    return {
        "user": settings.PG_USER,
        "password": settings.PG_PASSWORD,
        "database": "exports_test_database",
        "schema": "exports_test_schema",
        "host": settings.PG_HOST,
        "port": settings.PG_PORT,
    }


@pytest.fixture
def setup_test_db(postgres_config):
    connection = psycopg2.connect(
        user=postgres_config["user"],
        password=postgres_config["password"],
        host=postgres_config["host"],
        port=postgres_config["port"],
    )
    connection.set_session(autocommit=True)

    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("SELECT 1 FROM pg_database WHERE datname = %s"), (postgres_config["database"],))

        if cursor.fetchone() is None:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(postgres_config["database"])))

    connection.close()

    # We need a new connection to connect to the database we just created.
    connection = psycopg2.connect(
        user=postgres_config["user"],
        password=postgres_config["password"],
        host=postgres_config["host"],
        port=postgres_config["port"],
        database=postgres_config["database"],
    )
    connection.set_session(autocommit=True)

    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(postgres_config["schema"])))

    yield

    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(postgres_config["schema"])))

    connection.close()

    # We need a new connection to drop the database, as we cannot drop the current database.
    connection = psycopg2.connect(
        user=postgres_config["user"],
        password=postgres_config["password"],
        host=postgres_config["host"],
        port=postgres_config["port"],
    )
    connection.set_session(autocommit=True)

    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(postgres_config["database"])))

    connection.close()


@pytest.fixture
def postgres_connection(postgres_config, setup_test_db):
    connection = psycopg2.connect(
        user=postgres_config["user"],
        password=postgres_config["password"],
        database=postgres_config["database"],
        host=postgres_config["host"],
        port=postgres_config["port"],
    )

    yield connection

    connection.close()


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_insert_into_postgres_activity_inserts_data_into_postgres_table(
    activity_environment, postgres_connection, postgres_config
):
    """Test that the insert_into_postgres_activity function inserts data into a Postgres table."""

    data_interval_start = "2023-04-20 14:00:00"
    data_interval_end = "2023-04-25 15:00:00"

    # Generate a random team id integer. There's still a chance of a collision,
    # but it's very small.
    team_id = randint(1, 1000000)

    client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    # Add a materialized column such that we can verify that it is NOT included
    # in the export.
    await amaterialize("events", "$browser")

    # Create enough events to ensure we span more than 5MB, the smallest
    # multipart chunk size for multipart uploads to POSTGRES.
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
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "elements_chain": "this that and the other",
        }
        # NOTE: we have to do a lot here, otherwise we do not trigger a
        # multipart upload, and the minimum part chunk size is 5MB.
        for i in range(10000)
    ]

    events += [
        # Insert an events with an empty string in `properties` and
        # `person_properties` to ensure that we handle empty strings correctly.
        EventValues(
            {
                "uuid": str(uuid4()),
                "event": "test",
                "_timestamp": "2023-04-20 14:29:00",
                "timestamp": "2023-04-20 14:29:00.000000",
                "inserted_at": "2023-04-20 14:30:00.000000",
                "created_at": "2023-04-20 14:29:00.000000",
                "distinct_id": str(uuid4()),
                "person_id": str(uuid4()),
                "person_properties": None,
                "team_id": team_id,
                "properties": None,
                "elements_chain": "",
            }
        )
    ]

    # Insert some data into the `sharded_events` table.
    await insert_events(
        client=client,
        events=events,
    )

    # Insert some events before the hour and after the hour, as well as some
    # events from another team to ensure that we only export the events from
    # the team that the batch export is for.
    other_team_id = team_id + 1
    await insert_events(
        client=client,
        events=[
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-20 13:30:00",
                "_timestamp": "2023-04-20 13:30:00",
                "inserted_at": "2023-04-20 13:30:00.000000",
                "created_at": "2023-04-20 13:30:00.000000",
                "person_id": str(uuid4()),
                "distinct_id": str(uuid4()),
                "team_id": team_id,
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "elements_chain": "this is a comman, separated, list, of css selectors(?)",
            },
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-20 15:30:00",
                "_timestamp": "2023-04-20 13:30:00",
                "inserted_at": "2023-04-20 13:30:00.000000",
                "created_at": "2023-04-20 13:30:00.000000",
                "person_id": str(uuid4()),
                "distinct_id": str(uuid4()),
                "team_id": team_id,
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "elements_chain": "this is a comman, separated, list, of css selectors(?)",
            },
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-20 14:30:00",
                "_timestamp": "2023-04-20 14:30:00",
                "inserted_at": "2023-04-20 14:30:00.000000",
                "created_at": "2023-04-20 14:30:00.000000",
                "person_id": str(uuid4()),
                "distinct_id": str(uuid4()),
                "team_id": other_team_id,
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "elements_chain": "this is a comman, separated, list, of css selectors(?)",
            },
        ],
    )

    insert_inputs = PostgresInsertInputs(
        team_id=team_id,
        table_name="test_table",
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        **postgres_config,
    )

    with override_settings(BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
        await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    assert_events_in_postgres(
        connection=postgres_connection,
        schema=postgres_config["schema"],
        table_name="test_table",
        events=events,
    )

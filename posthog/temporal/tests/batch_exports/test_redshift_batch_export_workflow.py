from uuid import uuid4
from random import randint
import json
import datetime as dt
import os

import psycopg2
from psycopg2 import sql
import pytest
from django.conf import settings

from posthog.temporal.tests.batch_exports.base import (
    EventValues,
    amaterialize,
    insert_events,
)
from posthog.temporal.workflows.clickhouse import ClickHouseClient
from posthog.temporal.workflows.redshift_batch_export import (
    RedshiftInsertInputs,
    insert_into_redshift_activity,
)

REQUIRED_ENV_VARS = (
    "REDSHIFT_USER",
    "REDSHIFT_PASSWORD",
    "REDSHIFT_HOST",
)

pytestmark = pytest.mark.skipif(
    any(env_var not in os.environ for env_var in REQUIRED_ENV_VARS),
    reason="Redshift required env vars are not set",
)


def assert_events_in_redshift(connection, schema, table_name, events):
    """Assert provided events written to a given Postgres table."""

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
            "elements": json.dumps(elements_chain) if elements_chain else None,
            "event": event.get("event"),
            "ip": properties.get("$ip", None) if properties else None,
            "properties": json.dumps(properties) if properties else None,
            "set": properties.get("$set", None) if properties else None,
            "set_once": properties.get("$set_once", None) if properties else None,
            # Kept for backwards compatibility, but not exported anymore.
            "site_url": "",
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
def redshift_config():
    """Fixture to provide a default configuration for Redshift batch exports."""
    user = os.environ["REDSHIFT_USER"]
    password = os.environ["REDSHIFT_PASSWORD"]
    host = os.environ["REDSHIFT_HOST"]
    port = os.environ.get("REDSHIFT_PORT", "5439")

    return {
        "user": user,
        "password": password,
        "database": "exports_test_database",
        "schema": "exports_test_schema",
        "host": host,
        "port": int(port),
    }


@pytest.fixture
def setup_test_db(redshift_config):
    """Fixture to manage a database for Redshift exports."""
    connection = psycopg2.connect(
        user=redshift_config["user"],
        password=redshift_config["password"],
        host=redshift_config["host"],
        port=redshift_config["port"],
        database="dev",
    )
    connection.set_session(autocommit=True)

    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("SELECT 1 FROM pg_database WHERE datname = %s"), (redshift_config["database"],))

        if cursor.fetchone() is None:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(redshift_config["database"])))

    connection.close()

    # We need a new connection to connect to the database we just created.
    connection = psycopg2.connect(
        user=redshift_config["user"],
        password=redshift_config["password"],
        host=redshift_config["host"],
        port=redshift_config["port"],
        database=redshift_config["database"],
    )
    connection.set_session(autocommit=True)

    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(redshift_config["schema"])))

    yield

    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(redshift_config["schema"])))

    connection.close()

    # We need a new connection to drop the database, as we cannot drop the current database.
    connection = psycopg2.connect(
        user=redshift_config["user"],
        password=redshift_config["password"],
        host=redshift_config["host"],
        port=redshift_config["port"],
        database="dev",
    )
    connection.set_session(autocommit=True)

    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(redshift_config["database"])))

    connection.close()


@pytest.fixture
def psycopg2_connection(redshift_config, setup_test_db):
    """Fixture to manage a psycopg2 connection."""
    connection = psycopg2.connect(
        user=redshift_config["user"],
        password=redshift_config["password"],
        database=redshift_config["database"],
        host=redshift_config["host"],
        port=redshift_config["port"],
    )

    yield connection

    connection.close()


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_insert_into_redshift_activity_inserts_data_into_redshift_table(
    activity_environment, psycopg2_connection, redshift_config
):
    """Test that the insert_into_postgres_activity function inserts data into a Postgres table."""

    data_interval_start = "2023-04-20 14:00:00"
    data_interval_end = "2023-04-25 15:00:00"

    # Generate a random team id integer. There's still a chance of a collision,
    # but it's very small.
    team_id = randint(1, 1000000)

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
            "elements_chain": 'strong.pricingpage:attr__class="pricingpage"nth-child="1"nth-of-type="1"text="A question?";',
        }
        # NOTE: we have to do a lot here, otherwise we do not trigger a
        # multipart upload, and the minimum part chunk size is 5MB.
        for i in range(1000)
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
                "elements_chain": 'strong.pricingpage:attr__class="pricingpage"nth-child="1"nth-of-type="1"text="A question?";',
            }
        )
    ]

    ch_client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    # Insert some data into the `sharded_events` table.
    await insert_events(
        client=ch_client,
        events=events,
    )

    # Insert some events before the hour and after the hour, as well as some
    # events from another team to ensure that we only export the events from
    # the team that the batch export is for.
    other_team_id = team_id + 1
    await insert_events(
        client=ch_client,
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
                "elements_chain": 'strong.pricingpage:attr__class="pricingpage"nth-child="1"nth-of-type="1"text="A question?";',
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
                "elements_chain": 'strong.pricingpage:attr__class="pricingpage"nth-child="1"nth-of-type="1"text="A question?";',
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
                "elements_chain": 'strong.pricingpage:attr__class="pricingpage"nth-child="1"nth-of-type="1"text="A question?";',
            },
        ],
    )

    insert_inputs = RedshiftInsertInputs(
        team_id=team_id,
        table_name="test_table",
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        **redshift_config,
    )

    await activity_environment.run(insert_into_redshift_activity, insert_inputs)

    assert_events_in_redshift(
        connection=psycopg2_connection,
        schema=redshift_config["schema"],
        table_name="test_table",
        events=events,
    )

import datetime as dt
import json
import os
from random import randint
from uuid import uuid4

import psycopg2
import pytest
from django.conf import settings
from django.test import override_settings
from psycopg2 import sql
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.api.test.test_organization import acreate_organization
from posthog.api.test.test_team import acreate_team
from posthog.temporal.tests.batch_exports.base import (
    EventValues,
    amaterialize,
    insert_events,
)
from posthog.temporal.tests.batch_exports.fixtures import (
    acreate_batch_export,
    afetch_batch_export_runs,
)
from posthog.temporal.workflows.batch_exports import (
    create_export_run,
    update_export_run_status,
)
from posthog.temporal.workflows.clickhouse import ClickHouseClient
from posthog.temporal.workflows.redshift_batch_export import (
    RedshiftBatchExportInputs,
    RedshiftBatchExportWorkflow,
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
    """Assert provided events written to a given Redshift table."""

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
    """Fixture to provide a default configuration for Redshift batch exports.

    Reads required env vars to construct configuration.
    """
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
    """Fixture to manage a database for Redshift export testing.

    Managing a test database involves the following steps:
    1. Creating a test database.
    2. Initializing a connection to that database.
    3. Creating a test schema.
    4. Yielding the connection to be used in tests.
    5. After tests, drop the test schema and any tables in it.
    6. Drop the test database.
    """
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


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.parametrize("interval", ["hour", "day"])
async def test_redshift_export_workflow(
    redshift_config,
    psycopg2_connection,
    interval,
):
    """Test Redshift Export Workflow end-to-end."""
    table_name = "test_workflow_table"
    destination_data = {
        "type": "Redshift",
        "config": {**redshift_config, "table_name": table_name},
    }
    batch_export_data = {
        "name": "my-production-redshift-export",
        "destination": destination_data,
        "interval": interval,
    }

    organization = await acreate_organization("test")
    team = await acreate_team(organization=organization)
    batch_export = await acreate_batch_export(
        team_id=team.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": "test",
            "timestamp": "2023-04-25 13:30:00.000000",
            "created_at": "2023-04-25 13:30:00.000000",
            "inserted_at": "2023-04-25 13:30:00.000000",
            "_timestamp": "2023-04-25 13:30:00",
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team.pk,
            "properties": {
                "$browser": "Chrome",
                "$os": "Mac OS X",
                "$ip": "172.16.0.1",
                "$current_url": "https://app.posthog.com",
            },
            "distinct_id": str(uuid4()),
            "elements_chain": 'strong.pricingpage:attr__class="pricingpage"nth-child="1"nth-of-type="1"text="A question?";',
        },
        {
            "uuid": str(uuid4()),
            "event": "test",
            "timestamp": "2023-04-25 14:29:00.000000",
            "created_at": "2023-04-25 14:29:00.000000",
            "inserted_at": "2023-04-25 14:29:00.000000",
            "_timestamp": "2023-04-25 14:29:00",
            "person_id": str(uuid4()),
            "properties": {
                "$browser": "Chrome",
                "$os": "Mac OS X",
                "$current_url": "https://app.posthog.com",
                "$ip": "172.16.0.1",
            },
            "team_id": team.pk,
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "distinct_id": str(uuid4()),
            "elements_chain": 'strong.pricingpage:attr__class="pricingpage"nth-child="1"nth-of-type="1"text="A question?";',
        },
    ]

    if interval == "day":
        # Add an event outside the hour range but within the day range to ensure it's exported too.
        events_outside_hour: list[EventValues] = [
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-25 00:30:00.000000",
                "created_at": "2023-04-25 00:30:00.000000",
                "inserted_at": "2023-04-25 00:30:00.000000",
                "_timestamp": "2023-04-25 00:30:00",
                "person_id": str(uuid4()),
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "team_id": team.pk,
                "properties": {
                    "$browser": "Chrome",
                    "$os": "Mac OS X",
                    "$current_url": "https://app.posthog.com",
                    "$ip": "172.16.0.1",
                },
                "distinct_id": str(uuid4()),
                "elements_chain": 'strong.pricingpage:attr__class="pricingpage"nth-child="1"nth-of-type="1"text="A question?";',
            }
        ]
        events += events_outside_hour

    ch_client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    await insert_events(
        client=ch_client,
        events=events,
    )

    workflow_id = str(uuid4())
    inputs = RedshiftBatchExportInputs(
        team_id=team.pk,
        batch_export_id=str(batch_export.id),
        data_interval_end="2023-04-25 14:30:00.000000",
        interval=interval,
        **batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[RedshiftBatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_redshift_activity,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with override_settings(BATCH_EXPORT_REDSHIFT_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
                await activity_environment.client.execute_workflow(
                    RedshiftBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=10),
                )

    runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    assert_events_in_redshift(psycopg2_connection, redshift_config["schema"], table_name, events)

import datetime as dt
import json
import os
import warnings
from random import randint
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from django.conf import settings
from django.test import override_settings
from psycopg import sql
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.batch_exports.batch_exports import (
    create_export_run,
    update_export_run_status,
)
from posthog.temporal.batch_exports.redshift_batch_export import (
    RedshiftBatchExportInputs,
    RedshiftBatchExportWorkflow,
    RedshiftInsertInputs,
    insert_into_redshift_activity,
    remove_escaped_whitespace_recursive,
)
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
    afetch_batch_export_runs,
)

REQUIRED_ENV_VARS = (
    "REDSHIFT_USER",
    "REDSHIFT_PASSWORD",
    "REDSHIFT_HOST",
)

MISSING_REQUIRED_ENV_VARS = any(env_var not in os.environ for env_var in REQUIRED_ENV_VARS)


pytestmark = [pytest.mark.django_db, pytest.mark.asyncio]


async def assert_events_in_redshift(connection, schema, table_name, events, exclude_events: list[str] | None = None):
    """Assert provided events written to a given Redshift table."""

    inserted_events = []

    async with connection.cursor() as cursor:
        await cursor.execute(
            sql.SQL("SELECT * FROM {} ORDER BY event, timestamp").format(sql.Identifier(schema, table_name))
        )
        columns = [column.name for column in cursor.description]

        for row in await cursor.fetchall():
            event = dict(zip(columns, row))
            event["timestamp"] = dt.datetime.fromisoformat(event["timestamp"].isoformat())
            inserted_events.append(event)

    expected_events = []
    for event in events:
        event_name = event.get("event")

        if exclude_events is not None and event_name in exclude_events:
            continue

        raw_properties = event.get("properties", None)
        properties = remove_escaped_whitespace_recursive(raw_properties) if raw_properties else None
        expected_event = {
            "distinct_id": event.get("distinct_id"),
            "elements": "",
            "event": event_name,
            "ip": properties.get("$ip", None) if properties else None,
            "properties": json.dumps(properties, ensure_ascii=False) if properties else None,
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

    expected_events.sort(key=lambda x: (x["event"], x["timestamp"]))

    assert len(inserted_events) == len(expected_events)
    # First check one event, the first one, so that we can get a nice diff if
    # the included data is different.
    assert inserted_events[0] == expected_events[0]
    assert inserted_events == expected_events


@pytest.fixture
def redshift_config():
    """Fixture to provide a default configuration for Redshift batch exports.

    Reads required env vars to construct configuration, but if not present
    we default to local development PostgreSQL database, which should be mostly compatible.
    """
    if MISSING_REQUIRED_ENV_VARS:
        user = settings.PG_USER
        password = settings.PG_PASSWORD
        host = settings.PG_HOST
        port = int(settings.PG_PORT)
        warnings.warn("Missing required Redshift env vars. Running tests against local PG database.", stacklevel=1)

    else:
        user = os.environ["REDSHIFT_USER"]
        password = os.environ["REDSHIFT_PASSWORD"]
        host = os.environ["REDSHIFT_HOST"]
        port = os.environ.get("REDSHIFT_PORT", "5439")

    return {
        "user": user,
        "password": password,
        "database": "posthog_batch_exports_test_2",
        "schema": "exports_test_schema",
        "host": host,
        "port": int(port),
    }


@pytest.fixture
def postgres_config(redshift_config):
    """We shadow this name so that setup_postgres_test_db works with Redshift."""
    psycopg._encodings._py_codecs["UNICODE"] = "utf-8"
    psycopg._encodings.py_codecs.update((k.encode(), v) for k, v in psycopg._encodings._py_codecs.items())

    yield redshift_config


@pytest_asyncio.fixture
async def psycopg_connection(redshift_config, setup_postgres_test_db):
    """Fixture to manage a psycopg2 connection."""
    connection = await psycopg.AsyncConnection.connect(
        user=redshift_config["user"],
        password=redshift_config["password"],
        dbname=redshift_config["database"],
        host=redshift_config["host"],
        port=redshift_config["port"],
    )
    connection.prepare_threshold = None

    yield connection

    await connection.close()


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
async def test_insert_into_redshift_activity_inserts_data_into_redshift_table(
    clickhouse_client, activity_environment, psycopg_connection, redshift_config, exclude_events
):
    """Test that the insert_into_redshift_activity function inserts data into a Redshift table.

    We use the generate_test_events_in_clickhouse function to generate several sets
    of events. Some of these sets are expected to be exported, and others not. Expected
    events are those that:
    * Are created for the team_id of the batch export.
    * Are created in the date range of the batch export.
    * Are not duplicates of other events that are in the same batch.
    * Do not have an event name contained in the batch export's exclude_events.

    Once we have these events, we pass them to the assert_events_in_redshift function to check
    that they appear in the expected Redshift table.
    """
    data_interval_start = dt.datetime(2023, 4, 20, 14, 0, 0, tzinfo=dt.timezone.utc)
    data_interval_end = dt.datetime(2023, 4, 25, 15, 0, 0, tzinfo=dt.timezone.utc)

    # Generate a random team id integer. There's still a chance of a collision,
    # but it's very small.
    team_id = randint(1, 1000000)

    (events, _, _) = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=1000,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={
            "$browser": "Chrome",
            "$os": "Mac OS X",
            "whitespace": "hi\t\n\r\f\bhi",
            "nested_whitespace": {"whitespace": "hi\t\n\r\f\bhi"},
            "sequence": {"mucho_whitespace": ["hi", "hi\t\n\r\f\bhi", "hi\t\n\r\f\bhi", "hi"]},
            "multi-byte": "é",
        },
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )

    (events_with_no_properties, _, _) = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=5,
        count_outside_range=0,
        count_other_team=0,
        properties=None,
        person_properties=None,
    )

    if exclude_events:
        for event_name in exclude_events:
            await generate_test_events_in_clickhouse(
                client=clickhouse_client,
                team_id=team_id,
                start_time=data_interval_start,
                end_time=data_interval_end,
                count=5,
                count_outside_range=0,
                count_other_team=0,
                event_name=event_name,
            )

    insert_inputs = RedshiftInsertInputs(
        team_id=team_id,
        table_name="test_table",
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        **redshift_config,
    )

    await activity_environment.run(insert_into_redshift_activity, insert_inputs)

    await assert_events_in_redshift(
        connection=psycopg_connection,
        schema=redshift_config["schema"],
        table_name="test_table",
        events=events + events_with_no_properties,
        exclude_events=exclude_events,
    )


@pytest.fixture
def table_name(ateam, interval):
    return f"test_workflow_table_{ateam.pk}_{interval}"


@pytest_asyncio.fixture
async def redshift_batch_export(ateam, table_name, redshift_config, interval, exclude_events, temporal_client):
    destination_data = {
        "type": "Redshift",
        "config": {**redshift_config, "table_name": table_name, "exclude_events": exclude_events},
    }
    batch_export_data = {
        "name": "my-production-redshift-export",
        "destination": destination_data,
        "interval": interval,
    }

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


@pytest.mark.parametrize("interval", ["hour", "day"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
async def test_redshift_export_workflow(
    clickhouse_client,
    redshift_config,
    psycopg_connection,
    interval,
    redshift_batch_export,
    ateam,
    exclude_events,
    table_name,
):
    """Test Redshift Export Workflow end-to-end.

    The workflow should update the batch export run status to completed and produce the expected
    records to the provided Redshift instance.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")
    data_interval_start = data_interval_end - redshift_batch_export.interval_time_delta

    (events, _, _) = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=100,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )

    if exclude_events:
        for event_name in exclude_events:
            await generate_test_events_in_clickhouse(
                client=clickhouse_client,
                team_id=ateam.pk,
                start_time=data_interval_start,
                end_time=data_interval_end,
                count=5,
                count_outside_range=0,
                count_other_team=0,
                event_name=event_name,
            )

    workflow_id = str(uuid4())
    inputs = RedshiftBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(redshift_batch_export.id),
        data_interval_end="2023-04-25 14:30:00.000000",
        interval=interval,
        **redshift_batch_export.destination.config,
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

    runs = await afetch_batch_export_runs(batch_export_id=redshift_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    await assert_events_in_redshift(
        psycopg_connection,
        redshift_config["schema"],
        table_name,
        events=events,
        exclude_events=exclude_events,
    )


@pytest.mark.parametrize(
    "value,expected",
    [
        ([1, 2, 3], [1, 2, 3]),
        ("hi\t\n\r\f\bhi", "hi hi"),
        ([["\t\n\r\f\b"]], [[""]]),
        (("\t\n\r\f\b",), ("",)),
        ({"\t\n\r\f\b"}, {""}),
        ({"key": "\t\n\r\f\b"}, {"key": ""}),
        ({"key": ["\t\n\r\f\b"]}, {"key": [""]}),
    ],
)
def test_remove_escaped_whitespace_recursive(value, expected):
    """Test we remove some whitespace values."""
    assert remove_escaped_whitespace_recursive(value) == expected

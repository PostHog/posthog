import asyncio
import datetime as dt
import json
from random import randint
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from django.conf import settings
from django.test import override_settings
from psycopg import sql
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.batch_exports.service import BatchExportSchema
from posthog.temporal.batch_exports.batch_exports import (
    create_export_run,
    iter_records,
    update_export_run_status,
)
from posthog.temporal.batch_exports.clickhouse import ClickHouseClient
from posthog.temporal.batch_exports.postgres_batch_export import (
    PostgresBatchExportInputs,
    PostgresBatchExportWorkflow,
    PostgresInsertInputs,
    insert_into_postgres_activity,
    postgres_default_fields,
)
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
    afetch_batch_export_runs,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
]


async def assert_clickhouse_records_in_postgres(
    postgres_connection,
    clickhouse_client: ClickHouseClient,
    schema_name: str,
    table_name: str,
    team_id: int,
    batch_export_schema: BatchExportSchema | None,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
):
    """Assert expected records are written to a given PostgreSQL table.

    The steps this function takes to assert records are written are:
    1. Read all records inserted into given PostgreSQL table.
    2. Cast records read from PostgreSQL to a Python list of dicts.
    3. Assert records read from PostgreSQL have the expected column names.
    4. Read all records that were supposed to be inserted from ClickHouse.
    5. Cast records returned by ClickHouse to a Python list of dicts.
    6. Compare each record returned by ClickHouse to each record read from PostgreSQL.

    Caveats:
    * Casting records to a Python list of dicts means losing some type precision.
    * Reading records from ClickHouse could be hiding bugs in the `iter_records` function and related.
        * `iter_records` has its own set of related unit tests to control for this.

    Arguments:
        postgres_connection: A PostgreSQL connection used to read inserted events.
        clickhouse_client: A ClickHouseClient used to read events that are expected to be inserted.
        schema_name: PostgreSQL schema name.
        table_name: PostgreSQL table name.
        team_id: The ID of the team that we are testing events for.
        batch_export_schema: Custom schema used in the batch export.
    """
    inserted_records = []

    async with postgres_connection.cursor() as cursor:
        await cursor.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(schema_name, table_name)))
        columns = [column.name for column in cursor.description]

        for row in await cursor.fetchall():
            event = dict(zip(columns, row))
            inserted_records.append(event)

    if batch_export_schema is not None:
        schema_column_names = [field["alias"] for field in batch_export_schema["fields"]]
    else:
        schema_column_names = [field["alias"] for field in postgres_default_fields()]

    expected_records = []
    for records in iter_records(
        client=clickhouse_client,
        team_id=team_id,
        interval_start=data_interval_start.isoformat(),
        interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        include_events=include_events,
        fields=batch_export_schema["fields"] if batch_export_schema is not None else postgres_default_fields(),
        extra_query_parameters=batch_export_schema["values"] if batch_export_schema is not None else None,
    ):
        for record in records.select(schema_column_names).to_pylist():
            expected_record = {}

            for k, v in record.items():
                if k not in schema_column_names or k == "_inserted_at" or k == "bq_ingested_timestamp":
                    # _inserted_at is not exported, only used for tracking progress.
                    # bq_ingested_timestamp cannot be compared as it comes from an unstable function.
                    continue

                if k in {"properties", "set", "set_once", "person_properties"} and v is not None:
                    expected_record[k] = json.loads(v)
                elif isinstance(v, dt.datetime):
                    expected_record[k] = v.replace(tzinfo=dt.timezone.utc)
                else:
                    expected_record[k] = v

            expected_records.append(expected_record)

    inserted_column_names = [column_name for column_name in inserted_records[0].keys()].sort()
    expected_column_names = [column_name for column_name in expected_records[0].keys()].sort()

    assert inserted_column_names == expected_column_names
    assert inserted_records[0] == expected_records[0]
    assert inserted_records == expected_records


@pytest.fixture
def postgres_config():
    return {
        "user": settings.PG_USER,
        "password": settings.PG_PASSWORD,
        "database": "exports_test_database",
        "schema": "exports_test_schema",
        "host": settings.PG_HOST,
        "port": int(settings.PG_PORT),
    }


@pytest_asyncio.fixture
async def postgres_connection(postgres_config, setup_postgres_test_db):
    connection = await psycopg.AsyncConnection.connect(
        user=postgres_config["user"],
        password=postgres_config["password"],
        dbname=postgres_config["database"],
        host=postgres_config["host"],
        port=postgres_config["port"],
    )

    yield connection

    await connection.close()


TEST_SCHEMAS = [
    {
        "fields": [
            {"expression": "event", "alias": "event"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
            {"expression": "nullIf(properties, '')", "alias": "all_properties"},
        ],
        "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
    },
    {
        "fields": [
            {"expression": "event", "alias": "event"},
            {"expression": "inserted_at", "alias": "inserted_at"},
            {"expression": "toInt8(1 + 1)", "alias": "two"},
        ],
        "values": {},
    },
    None,
]


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("batch_export_schema", TEST_SCHEMAS)
async def test_insert_into_postgres_activity_inserts_data_into_postgres_table(
    clickhouse_client, activity_environment, postgres_connection, postgres_config, exclude_events, batch_export_schema
):
    """Test that the insert_into_postgres_activity function inserts data into a PostgreSQL table.

    We use the generate_test_events_in_clickhouse function to generate several sets
    of events. Some of these sets are expected to be exported, and others not. Expected
    events are those that:
    * Are created for the team_id of the batch export.
    * Are created in the date range of the batch export.
    * Are not duplicates of other events that are in the same batch.
    * Do not have an event name contained in the batch export's exclude_events.

    Once we have these events, we pass them to the assert_events_in_postgres function to check
    that they appear in the expected PostgreSQL table. This function utilizes the local
    development postgres instance for testing. But we setup and manage our own database
    to avoid conflicting with PostHog itself.
    """
    data_interval_start = dt.datetime(2023, 4, 20, 14, 0, 0, tzinfo=dt.timezone.utc)
    data_interval_end = dt.datetime(2023, 4, 25, 15, 0, 0, tzinfo=dt.timezone.utc)

    # Generate a random team id integer. There's still a chance of a collision,
    # but it's very small.
    team_id = randint(1, 1000000)

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10000,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=5,
        count_outside_range=0,
        count_other_team=0,
        properties=None,
        person_properties=None,
        event_name="test-no-prop-{i}",
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

    insert_inputs = PostgresInsertInputs(
        team_id=team_id,
        table_name="test_table",
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_schema=batch_export_schema,
        **postgres_config,
    )

    with override_settings(BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
        await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name="test_table",
        team_id=team_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_schema=batch_export_schema,
        exclude_events=exclude_events,
    )


@pytest.fixture
def table_name(ateam, interval):
    return f"test_workflow_table_{ateam.pk}_{interval}"


@pytest_asyncio.fixture
async def postgres_batch_export(ateam, table_name, postgres_config, interval, exclude_events, temporal_client):
    destination_data = {
        "type": "Postgres",
        "config": {**postgres_config, "table_name": table_name, "exclude_events": exclude_events},
    }
    batch_export_data = {
        "name": "my-production-postgres-export",
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
@pytest.mark.parametrize("batch_export_schema", TEST_SCHEMAS)
async def test_postgres_export_workflow(
    clickhouse_client,
    postgres_config,
    postgres_connection,
    postgres_batch_export,
    interval,
    exclude_events,
    ateam,
    table_name,
    batch_export_schema,
):
    """Test Postgres Export Workflow end-to-end by using a local PG database.

    The workflow should update the batch export run status to completed and produce the expected
    records to the local development PostgreSQL database.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")
    data_interval_start = data_interval_end - postgres_batch_export.interval_time_delta

    await generate_test_events_in_clickhouse(
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
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        **postgres_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[PostgresBatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_postgres_activity,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with override_settings(BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
                await activity_environment.client.execute_workflow(
                    PostgresBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=10),
                )

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_schema=batch_export_schema,
        exclude_events=exclude_events,
    )


async def test_postgres_export_workflow_handles_insert_activity_errors(ateam, postgres_batch_export, interval):
    """Test that Postgres Export Workflow can gracefully handle errors when inserting Postgres data."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid4())
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **postgres_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_postgres_activity")
    async def insert_into_postgres_activity_mocked(_: PostgresInsertInputs) -> str:
        raise ValueError("A useful error message")

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[PostgresBatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_postgres_activity_mocked,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    PostgresBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "FailedRetryable"
    assert run.latest_error == "ValueError: A useful error message"


async def test_postgres_export_workflow_handles_insert_activity_non_retryable_errors(
    ateam, postgres_batch_export, interval
):
    """Test that Postgres Export Workflow can gracefully handle non-retryable errors when inserting Postgres data."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid4())
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **postgres_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_postgres_activity")
    async def insert_into_postgres_activity_mocked(_: PostgresInsertInputs) -> str:
        class InsufficientPrivilege(Exception):
            pass

        raise InsufficientPrivilege("A useful error message")

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[PostgresBatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_postgres_activity_mocked,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    PostgresBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert run.latest_error == "InsufficientPrivilege: A useful error message"


async def test_postgres_export_workflow_handles_cancellation(ateam, postgres_batch_export, interval):
    """Test that Postgres Export Workflow can gracefully handle cancellations when inserting Postgres data."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid4())
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **postgres_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_postgres_activity")
    async def never_finish_activity(_: PostgresInsertInputs) -> str:
        while True:
            activity.heartbeat()
            await asyncio.sleep(1)

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[PostgresBatchExportWorkflow],
            activities=[
                create_export_run,
                never_finish_activity,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await activity_environment.client.start_workflow(
                PostgresBatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            await asyncio.sleep(5)
            await handle.cancel()

            with pytest.raises(WorkflowFailureError):
                await handle.result()

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Cancelled"
    assert run.latest_error == "Cancelled"

import asyncio
import datetime as dt
import json
import operator
import uuid

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

from posthog import constants
from posthog.batch_exports.service import (
    BackfillDetails,
    BatchExportModel,
    BatchExportSchema,
)
from posthog.temporal.batch_exports.batch_exports import (
    finish_batch_export_run,
    iter_model_records,
    start_batch_export_run,
)
from posthog.temporal.batch_exports.postgres_batch_export import (
    MissingPrimaryKeyError,
    PostgresBatchExportInputs,
    PostgresBatchExportWorkflow,
    PostgresInsertInputs,
    insert_into_postgres_activity,
    postgres_default_fields,
)
from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.tests.batch_exports.utils import mocked_start_batch_export_run
from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
    afetch_batch_export_runs,
)
from posthog.temporal.tests.utils.persons import (
    generate_test_person_distinct_id2_in_clickhouse,
    generate_test_persons_in_clickhouse,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
]

EXPECTED_PERSONS_BATCH_EXPORT_FIELDS = [
    "team_id",
    "distinct_id",
    "person_id",
    "properties",
    "person_version",
    "person_distinct_id_version",
    "created_at",
    "_inserted_at",
]


async def assert_clickhouse_records_in_postgres(
    postgres_connection,
    clickhouse_client: ClickHouseClient,
    schema_name: str,
    table_name: str,
    team_id: int,
    batch_export_model: BatchExportModel | BatchExportSchema | None,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    sort_key: str = "event",
    backfill_details: BackfillDetails | None = None,
    expected_fields: list[str] | None = None,
):
    """Assert expected records are written to a given PostgreSQL table.

    The steps this function takes to assert records are written are:
    1. Read all records inserted into given PostgreSQL table.
    2. Cast records read from PostgreSQL to a Python list of dicts.
    3. Assert records read from PostgreSQL have the expected column names.
    4. Read all records that were supposed to be inserted from ClickHouse.
    5. Cast records returned by ClickHouse to a Python list of dicts.
    6. Compare each record returned by ClickHouse to each record read from PostgreSQL.

    Arguments:
        postgres_connection: A PostgreSQL connection used to read inserted events.
        clickhouse_client: A ClickHouseClient used to read events that are expected to be inserted.
        schema_name: PostgreSQL schema name.
        table_name: PostgreSQL table name.
        team_id: The ID of the team that we are testing events for.
        batch_export_schema: Custom schema used in the batch export.
        expected_fields: The expected fields to be exported.
    """
    inserted_records = []

    async with postgres_connection.cursor() as cursor:
        await cursor.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(schema_name, table_name)))
        columns = [column.name for column in cursor.description]

        for row in await cursor.fetchall():
            event = dict(zip(columns, row))
            inserted_records.append(event)

    schema_column_names = (
        expected_fields if expected_fields is not None else [field["alias"] for field in postgres_default_fields()]
    )
    if batch_export_model is not None and expected_fields is None:
        if isinstance(batch_export_model, BatchExportModel):
            batch_export_schema = batch_export_model.schema
        else:
            batch_export_schema = batch_export_model

        if batch_export_schema is not None:
            schema_column_names = [field["alias"] for field in batch_export_schema["fields"]]
        elif isinstance(batch_export_model, BatchExportModel) and batch_export_model.name == "persons":
            schema_column_names = EXPECTED_PERSONS_BATCH_EXPORT_FIELDS

    expected_records = []
    async for record_batch in iter_model_records(
        client=clickhouse_client,
        model=batch_export_model,
        team_id=team_id,
        interval_start=data_interval_start.isoformat(),
        interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        include_events=include_events,
        destination_default_fields=postgres_default_fields(),
        backfill_details=backfill_details,
        use_latest_schema=True,
    ):
        for record in record_batch.select(schema_column_names).to_pylist():
            expected_record = {}

            for k, v in record.items():
                if k not in schema_column_names or k == "_inserted_at" or k == "bq_ingested_timestamp":
                    # _inserted_at is not exported, only used for tracking progress.
                    # bq_ingested_timestamp cannot be compared as it comes from an unstable function.
                    continue

                if isinstance(v, str):
                    v = v.replace("\\u0000", "")
                elif isinstance(v, bytes):
                    v = v.replace(b"\\u0000", b"")

                if k in {"properties", "set", "set_once", "person_properties", "elements"} and v is not None:
                    expected_record[k] = json.loads(v)
                elif isinstance(v, dt.datetime):
                    expected_record[k] = v.replace(tzinfo=dt.UTC)
                else:
                    expected_record[k] = v

            expected_records.append(expected_record)

    inserted_column_names = list(inserted_records[0].keys())
    expected_column_names = list(expected_records[0].keys())
    inserted_column_names.sort()
    expected_column_names.sort()

    inserted_records.sort(key=operator.itemgetter(sort_key))
    expected_records.sort(key=operator.itemgetter(sort_key))

    assert inserted_column_names == expected_column_names
    assert len(inserted_records) == len(expected_records)
    assert inserted_records[0] == expected_records[0]
    assert inserted_records == expected_records


@pytest.fixture
def test_properties(request):
    """Include a \u0000 unicode escape sequence in properties."""
    return {"$browser": "Chrome", "$os": "Mac OS X", "unicode": "\u0000"}


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
        autocommit=True,
    )

    yield connection

    await connection.close()


TEST_MODELS: list[BatchExportModel | BatchExportSchema | None] = [
    BatchExportModel(
        name="a-custom-model",
        schema={
            "fields": [
                {"expression": "event", "alias": "event"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
                {"expression": "nullIf(properties, '')", "alias": "all_properties"},
            ],
            "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
        },
    ),
    BatchExportModel(name="events", schema=None),
    BatchExportModel(
        name="events",
        schema=None,
        filters=[
            {"key": "$browser", "operator": "exact", "type": "event", "value": ["Chrome"]},
            {"key": "$os", "operator": "exact", "type": "event", "value": ["Mac OS X"]},
        ],
    ),
    BatchExportModel(name="persons", schema=None),
    {
        "fields": [
            {"expression": "event", "alias": "event"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
            {"expression": "nullIf(properties, '')", "alias": "all_properties"},
        ],
        "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
    },
    None,
]


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_insert_into_postgres_activity_inserts_data_into_postgres_table(
    clickhouse_client,
    activity_environment,
    postgres_connection,
    postgres_config,
    exclude_events,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
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
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    insert_inputs = PostgresInsertInputs(
        team_id=ateam.pk,
        table_name="test_table",
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **postgres_config,
    )

    with override_settings(BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
        await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name="test_table",
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        sort_key="person_id" if batch_export_model is not None and batch_export_model.name == "persons" else "event",
    )


async def test_insert_into_postgres_activity_merges_data_in_follow_up_runs(
    clickhouse_client,
    activity_environment,
    postgres_connection,
    postgres_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_postgres_activity` merges new versions of rows.

    This unit tests looks at the mutability handling capabilities of the aforementioned activity.
    We will generate a new entry in the persons table for half of the persons exported in a first
    run of the activity. We expect the new entries to have replaced the old ones in PostgreSQL after
    the second run.
    """
    model = BatchExportModel(name="persons", schema=None)

    insert_inputs = PostgresInsertInputs(
        team_id=ateam.pk,
        table_name=f"test_insert_activity_mutability_table__{ateam.pk}",
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        **postgres_config,
    )

    await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=f"test_insert_activity_mutability_table__{ateam.pk}",
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="person_id",
    )

    _, persons_to_export_created = generate_test_data

    for old_person in persons_to_export_created[: len(persons_to_export_created) // 2]:
        new_person_id = uuid.uuid4()
        new_person, _ = await generate_test_persons_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=data_interval_start,
            end_time=data_interval_end,
            person_id=new_person_id,
            count=1,
            properties={"utm_medium": "referral", "$initial_os": "Linux", "new_property": "Something"},
        )

        await generate_test_person_distinct_id2_in_clickhouse(
            clickhouse_client,
            ateam.pk,
            person_id=uuid.UUID(new_person[0]["id"]),
            distinct_id=old_person["distinct_id"],
            version=old_person["version"] + 1,
            timestamp=old_person["_timestamp"],
        )

    await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=f"test_insert_activity_mutability_table__{ateam.pk}",
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="person_id",
    )


@pytest.fixture
def table_name(ateam, interval):
    return f"test_table_{ateam.pk}_{interval}"


@pytest_asyncio.fixture
async def persons_table_without_primary_key(postgres_connection, postgres_config, table_name):
    """Managed a table for a persons batch export without a primary key."""
    self_managed_table_name = table_name + f"_self_managed_{uuid.uuid4().hex}"

    async with postgres_connection.transaction():
        async with postgres_connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL(
                    """
                    CREATE TABLE {table} (
                        team_id BIGINT,
                        distinct_id TEXT,
                        person_id TEXT,
                        properties JSONB,
                        person_distinct_id_version BIGINT,
                        person_version BIGINT,
                        created_at TIMESTAMP,
                        updated_at TIMESTAMP
                    )
                    """
                ).format(table=sql.Identifier(postgres_config["schema"], self_managed_table_name))
            )

    yield self_managed_table_name

    async with postgres_connection.transaction():
        async with postgres_connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL("DROP TABLE IF EXISTS {table}").format(
                    table=sql.Identifier(postgres_config["schema"], self_managed_table_name)
                )
            )


@pytest.mark.parametrize("model", [BatchExportModel(name="persons", schema=None)])
async def test_insert_into_postgres_activity_inserts_fails_on_missing_primary_key(
    activity_environment,
    postgres_config,
    exclude_events,
    model: BatchExportModel | BatchExportSchema | None,
    data_interval_start,
    data_interval_end,
    ateam,
    generate_test_data,
    persons_table_without_primary_key,
):
    """Test the insert_into_postgres_activity function fails when missing a primary key.

    We use a self-managed, previously created postgresql table to export persons data to.
    Since this table does not have a primary key, the merge query should fail.

    This error should only occur if the table is created outside the batch export.
    """
    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    insert_inputs = PostgresInsertInputs(
        team_id=ateam.pk,
        table_name=persons_table_without_primary_key,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **postgres_config,
    )

    with pytest.raises(MissingPrimaryKeyError):
        with override_settings(BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
            await activity_environment.run(insert_into_postgres_activity, insert_inputs)


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
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_postgres_export_workflow(
    clickhouse_client,
    postgres_config,
    postgres_connection,
    postgres_batch_export,
    interval,
    exclude_events,
    ateam,
    table_name,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
):
    """Test Postgres Export Workflow end-to-end by using a local PG database.

    The workflow should update the batch export run status to completed and produce the expected
    records to the local development PostgreSQL database.
    """
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    workflow_id = str(uuid.uuid4())
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **postgres_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[PostgresBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_postgres_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with override_settings(BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
                await activity_environment.client.execute_workflow(
                    PostgresBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=10),
                )

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    events_to_export_created, persons_to_export_created = generate_test_data

    run = runs[0]
    assert run.status == "Completed"
    assert (
        run.records_completed == len(events_to_export_created)
        or run.records_completed == len(persons_to_export_created)
        or run.records_completed
        == len([event for event in events_to_export_created if event["properties"] is not None])
    )

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        sort_key="person_id" if batch_export_model is not None and batch_export_model.name == "persons" else "event",
    )


@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_postgres_export_workflow_without_events(
    clickhouse_client,
    postgres_config,
    postgres_connection,
    postgres_batch_export,
    interval,
    exclude_events,
    ateam,
    table_name,
    model: BatchExportModel | BatchExportSchema | None,
    data_interval_start,
    data_interval_end,
):
    """Test Postgres Export Workflow end-to-end without any events to export.

    The workflow should update the batch export run status to completed and set 0 as `records_completed`.
    """
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    workflow_id = str(uuid.uuid4())
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **postgres_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[PostgresBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_postgres_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with override_settings(BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
                await activity_environment.client.execute_workflow(
                    PostgresBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=10),
                )

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"
    assert run.records_completed == 0


@pytest.mark.parametrize(
    "data_interval_start",
    # This is hardcoded relative to the `data_interval_end` used in all or most tests, since that's also
    # passed to `generate_test_data` to determine the timestamp for the generated data.
    [dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(hours=24)],
    indirect=True,
)
@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="persons", schema=None)])
async def test_postgres_export_workflow_backfill_earliest_persons(
    ateam,
    clickhouse_client,
    postgres_config,
    postgres_connection,
    postgres_batch_export,
    interval,
    exclude_events,
    data_interval_start,
    data_interval_end,
    model,
    generate_test_data,
    table_name,
):
    """Test a `PostgresBatchExportWorkflow` backfilling the persons model.

    We expect persons outside the batch interval to also be backfilled (i.e. persons that were updated
    more than an hour ago) when setting `is_earliest_backfill=True`.
    """
    backfill_details = BackfillDetails(
        backfill_id=str(uuid.uuid4()),
        is_earliest_backfill=True,
        start_at=None,
        end_at=data_interval_end.isoformat(),
    )
    workflow_id = str(uuid.uuid4())
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_model=model,
        backfill_details=backfill_details,
        **postgres_batch_export.destination.config,
    )
    _, persons = generate_test_data

    # Ensure some data outside batch interval has been created
    assert any(
        data_interval_end - person["_timestamp"].replace(tzinfo=dt.UTC) > dt.timedelta(hours=12) for person in persons
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[PostgresBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_postgres_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await activity_environment.client.execute_workflow(
                PostgresBatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(minutes=10),
            )

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"
    assert run.data_interval_start is None

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        sort_key="person_id",
        backfill_details=backfill_details,
    )


async def test_postgres_export_workflow_handles_insert_activity_errors(ateam, postgres_batch_export, interval):
    """Test that Postgres Export Workflow can gracefully handle errors when inserting Postgres data."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
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
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[PostgresBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_postgres_activity_mocked,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    PostgresBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "FailedRetryable"
    assert run.latest_error == "ValueError: A useful error message"
    assert run.records_completed is None


async def test_postgres_export_workflow_handles_insert_activity_non_retryable_errors(
    ateam, postgres_batch_export, interval
):
    """Test that Postgres Export Workflow can gracefully handle non-retryable errors when inserting Postgres data."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
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
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[PostgresBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_postgres_activity_mocked,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    PostgresBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert run.latest_error == "InsufficientPrivilege: A useful error message"
    assert run.records_completed is None


async def test_postgres_export_workflow_handles_cancellation(ateam, postgres_batch_export, interval):
    """Test that Postgres Export Workflow can gracefully handle cancellations when inserting Postgres data."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
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
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[PostgresBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                never_finish_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await activity_environment.client.start_workflow(
                PostgresBatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
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
    assert run.records_completed is None


async def test_insert_into_postgres_activity_handles_person_schema_changes(
    clickhouse_client,
    activity_environment,
    postgres_connection,
    postgres_config,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_postgres_activity` handles changes to the
    person schema.

    If we update the schema of the persons model we export, we should still be
    able to export the data without breaking existing exports. For example, any
    new fields should not be added to the destination (in future we may want to
    allow this but for now we don't).

    To replicate this situation we first export the data with the original
    schema, then delete a column in the destination and then rerun the export.
    """
    model = BatchExportModel(name="persons", schema=None)

    insert_inputs = PostgresInsertInputs(
        team_id=ateam.pk,
        table_name=f"test_insert_activity_migration_table__{ateam.pk}",
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        **postgres_config,
    )

    await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=f"test_insert_activity_migration_table__{ateam.pk}",
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="person_id",
    )

    # Drop the created_at column from the PostgreSQL table
    async with postgres_connection.transaction():
        async with postgres_connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL("ALTER TABLE {table} DROP COLUMN created_at").format(
                    table=sql.Identifier(postgres_config["schema"], f"test_insert_activity_migration_table__{ateam.pk}")
                )
            )

    _, persons_to_export_created = generate_test_data

    for old_person in persons_to_export_created[: len(persons_to_export_created) // 2]:
        new_person_id = uuid.uuid4()
        new_person, _ = await generate_test_persons_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=data_interval_start,
            end_time=data_interval_end,
            person_id=new_person_id,
            count=1,
            properties={"utm_medium": "referral", "$initial_os": "Linux", "new_property": "Something"},
        )

        await generate_test_person_distinct_id2_in_clickhouse(
            clickhouse_client,
            ateam.pk,
            person_id=uuid.UUID(new_person[0]["id"]),
            distinct_id=old_person["distinct_id"],
            version=old_person["version"] + 1,
            timestamp=old_person["_timestamp"],
        )

    await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    # This time we don't expect there to be a created_at column
    expected_fields = [field for field in EXPECTED_PERSONS_BATCH_EXPORT_FIELDS if field != "created_at"]

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=f"test_insert_activity_migration_table__{ateam.pk}",
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="person_id",
        expected_fields=expected_fields,
    )


async def test_postgres_export_workflow_with_many_files(
    clickhouse_client,
    postgres_connection,
    interval,
    postgres_batch_export,
    ateam,
    exclude_events,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    postgres_config,
):
    """Test Postgres Export Workflow end-to-end with multiple file uploads.

    This test overrides the chunk size and sets it to 10 bytes to trigger multiple file uploads.
    We want to assert that all files are properly copied into the table. Of course, 10 bytes limit
    means we are uploading one file at a time, which is very inefficient. For this reason, this test
    can take longer, so we keep the event count low and bump the Workflow timeout.
    """

    model = BatchExportModel(name="events", schema=None)

    workflow_id = str(uuid.uuid4())
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_model=model,
        **postgres_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[PostgresBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_postgres_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with override_settings(
                BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES=10, CLICKHOUSE_MAX_BLOCK_SIZE_DEFAULT=10
            ):
                await activity_environment.client.execute_workflow(
                    PostgresBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(minutes=2),
                )

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=postgres_batch_export.destination.config["table_name"],
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        batch_export_model=model,
        sort_key="event",
    )

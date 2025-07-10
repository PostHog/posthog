import asyncio
import collections.abc
import dataclasses
import datetime as dt
import json
import operator
import re
import unittest.mock
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
from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
    afetch_batch_export_runs,
)
from posthog.temporal.tests.utils.persons import (
    generate_test_person_distinct_id2_in_clickhouse,
    generate_test_persons_in_clickhouse,
)
from products.batch_exports.backend.temporal.batch_exports import (
    finish_batch_export_run,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.postgres_batch_export import (
    MissingPrimaryKeyError,
    PostgresBatchExportInputs,
    PostgresBatchExportWorkflow,
    PostgresInsertInputs,
    PostgreSQLHeartbeatDetails,
    insert_into_postgres_activity,
    postgres_default_fields,
    remove_invalid_json,
)
from products.batch_exports.backend.temporal.spmc import (
    Producer,
    RecordBatchQueue,
    RecordBatchTaskError,
    SessionsRecordBatchModel,
)
from products.batch_exports.backend.tests.temporal.utils import (
    FlakyClickHouseClient,
    get_record_batch_from_queue,
    mocked_start_batch_export_run,
    remove_duplicates_from_records,
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
    "is_deleted",
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
    expect_duplicates: bool = False,
    primary_key: collections.abc.Sequence[str] | None = None,
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

    if batch_export_model is not None:
        if isinstance(batch_export_model, BatchExportModel):
            model_name = batch_export_model.name
            fields = batch_export_model.schema["fields"] if batch_export_model.schema is not None else None
            filters = batch_export_model.filters
            extra_query_parameters = (
                batch_export_model.schema["values"] if batch_export_model.schema is not None else None
            )
        else:
            model_name = "custom"
            fields = batch_export_model["fields"]
            filters = None
            extra_query_parameters = batch_export_model["values"]
    else:
        model_name = "events"
        extra_query_parameters = None
        fields = None
        filters = None

    expected_records = []
    queue = RecordBatchQueue()
    if model_name == "sessions":
        producer = Producer(model=SessionsRecordBatchModel(team_id))
    else:
        producer = Producer()

    producer_task = await producer.start(
        queue=queue,
        model_name=model_name,
        team_id=team_id,
        full_range=(data_interval_start, data_interval_end),
        done_ranges=[],
        fields=fields,
        filters=filters,
        destination_default_fields=postgres_default_fields(),
        exclude_events=exclude_events,
        include_events=include_events,
        is_backfill=backfill_details is not None,
        backfill_details=backfill_details,
        extra_query_parameters=extra_query_parameters,
    )
    while True:
        record_batch = await get_record_batch_from_queue(queue, producer_task)

        if record_batch is None:
            break

        select = record_batch.column_names
        if expected_fields:
            select = expected_fields

        for record in record_batch.select(select).to_pylist():
            expected_record = {}

            for k, v in record.items():
                if k == "_inserted_at" or k == "bq_ingested_timestamp":
                    # _inserted_at is not exported, only used for tracking progress.
                    # bq_ingested_timestamp cannot be compared as it comes from an unstable function.
                    continue

                # Remove \u0000 from strings and bytes (we perform the same operation in the COPY query)
                if isinstance(v, str):
                    v = re.sub(r"(?<!\\)\\u0000", "", v)
                elif isinstance(v, bytes):
                    v = re.sub(rb"(?<!\\)\\u0000", b"", v)
                # We remove unpaired surrogates in PostgreSQL, so we have to remove them here too so
                # that comparison doesn't fail. The problem is that at some point our unpaired surrogate gets
                # escaped (which is correct, as unpaired surrogates are not valid). But then the
                # comparison fails as in PostgreSQL we remove unpaired surrogates, not just escape them.
                # So, we hardcode replace the test properties. Not ideal, but this works as we get the
                # expected result in PostgreSQL and the comparison is still useful.
                if isinstance(v, str):
                    v = v.replace("\\ud83e\\udd23\\udd23", "\\ud83e\\udd23").replace(
                        "\\ud83e\\udd23\\ud83e", "\\ud83e\\udd23"
                    )

                if k in {"properties", "set", "set_once", "person_properties", "elements"} and v is not None:
                    expected_record[k] = json.loads(v)
                elif isinstance(v, dt.datetime):
                    expected_record[k] = v.replace(tzinfo=dt.UTC)
                else:
                    expected_record[k] = v

            expected_records.append(expected_record)

    if expect_duplicates:
        inserted_records = remove_duplicates_from_records(inserted_records, primary_key)

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
def test_properties(request, session_id):
    """Include some problematic properties."""
    try:
        return request.param
    except AttributeError:
        return {
            "$browser": "Chrome",
            "$os": "Mac OS X",
            "$session_id": session_id,
            "unicode_null": "\u0000",
            "emoji": "🤣",
            "newline": "\n",
        }


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
    BatchExportModel(name="sessions", schema=None),
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
    if (
        isinstance(model, BatchExportModel)
        and (model.name == "persons" or model.name == "sessions")
        and exclude_events is not None
    ):
        pytest.skip(f"Unnecessary test case as {model.name} batch export is not affected by 'exclude_events'")

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

    sort_key = "event"
    if batch_export_model is not None:
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

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
        sort_key=sort_key,
    )


@pytest.mark.parametrize("exclude_events", [None], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="events", schema=None)])
@pytest.mark.parametrize(
    "test_properties",
    [
        {
            "$browser": "Chrome",
            "$os": "Mac OS X",
            "emoji": "🤣",
            "newline": "\n",
            "unicode_null": "\u0000",
            "invalid_unicode": "\\u0000'",  # this has given us issues in the past
            "emoji_with_high_surrogate": "🤣\ud83e",
            "emoji_with_low_surrogate": "🤣\udd23",
            "emoji_with_high_surrogate_and_newline": "🤣\ud83e\n",
            "emoji_with_low_surrogate_and_newline": "🤣\udd23\n",
        }
    ],
    indirect=True,
)
async def test_insert_into_postgres_activity_handles_problematic_json(
    clickhouse_client,
    activity_environment,
    postgres_connection,
    postgres_config,
    exclude_events,
    model: BatchExportModel,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Sometimes users send us invalid JSON. We want to test that we handle this gracefully.

    We only use the event model here since custom models with expressions such as JSONExtractString will still fail, as
    ClickHouse is not able to parse invalid JSON. There's not much we can do about this case.
    """

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model = model

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

    sort_key = "event"
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
        sort_key=sort_key,
    )


async def test_insert_into_postgres_activity_merges_persons_data_in_follow_up_runs(
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
    table_name = f"test_insert_activity_mutability_table_persons_{ateam.pk}"

    insert_inputs = PostgresInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
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
        table_name=table_name,
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
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="person_id",
    )


async def test_insert_into_postgres_activity_merges_sessions_data_in_follow_up_runs(
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
    We will generate a new entry in the sessions table after an initial run. We expect the new
    entry to have replaced the old ones in PostgreSQL after the second run.
    """
    model = BatchExportModel(name="sessions", schema=None)
    table_name = f"test_insert_activity_mutability_table_sessions_{ateam.pk}"

    insert_inputs = PostgresInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
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
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        sort_key="session_id",
    )

    events_to_export_created, _ = generate_test_data
    event = events_to_export_created[0]

    new_data_interval_start, new_data_interval_end = (
        data_interval_start + dt.timedelta(hours=1),
        data_interval_end + dt.timedelta(hours=1),
    )

    new_events, _, _ = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=new_data_interval_start,
        end_time=new_data_interval_end,
        count=1,
        count_outside_range=0,
        count_other_team=0,
        duplicate=False,
        properties=event["properties"],
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
        event_name=event["event"],
        table="sharded_events",
        insert_sessions=True,
    )

    insert_inputs.data_interval_start = new_data_interval_start.isoformat()
    insert_inputs.data_interval_end = new_data_interval_end.isoformat()

    await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=new_data_interval_start,
        data_interval_end=new_data_interval_end,
        batch_export_model=model,
        sort_key="session_id",
    )

    rows = []
    async with postgres_connection.cursor() as cursor:
        await cursor.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(postgres_config["schema"], table_name)))

        columns = [column.name for column in cursor.description]

        for row in await cursor.fetchall():
            event = dict(zip(columns, row))
            rows.append(event)

    new_event = new_events[0]
    new_event_properties = new_event["properties"] or {}
    assert len(rows) == 1
    assert rows[0]["session_id"] == new_event_properties["$session_id"]
    assert rows[0]["end_timestamp"] == dt.datetime.fromisoformat(new_event["timestamp"]).replace(tzinfo=dt.UTC)


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
                        updated_at TIMESTAMP,
                        is_deleted BOOLEAN
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
    if (
        isinstance(model, BatchExportModel)
        and (model.name == "persons" or model.name == "sessions")
        and exclude_events is not None
    ):
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

    sort_key = "event"
    if batch_export_model is not None:
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

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
        or (isinstance(model, BatchExportModel) and model.name == "sessions" and run.records_completed == 1)
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
        sort_key=sort_key,
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
    if (
        isinstance(model, BatchExportModel)
        and (model.name == "persons" or model.name == "sessions")
        and exclude_events is not None
    ):
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
    # This is set to 24 hours before the `data_interval_end` to ensure that the data created is outside the batch
    # interval.
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
        backfill_id=None,
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


@pytest.mark.parametrize("model", [BatchExportModel(name="persons", schema=None)])
async def test_insert_into_postgres_activity_completes_range_when_there_is_a_failure(
    clickhouse_client,
    activity_environment,
    postgres_connection,
    interval,
    postgres_batch_export,
    ateam,
    exclude_events,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    postgres_config,
    model,
):
    """Test that the insert_into_postgres_activity can resume from a failure using heartbeat details."""
    table_name = f"test_insert_activity_table_{ateam.pk}"

    events_to_create, persons_to_create = generate_test_data
    total_records = len(persons_to_create) if model.name == "persons" else len(events_to_create)
    # fail halfway through
    fail_after_records = total_records // 2

    heartbeat_details: list[PostgreSQLHeartbeatDetails] = []

    def track_heartbeat_details(*details):
        """Record heartbeat details received."""
        nonlocal heartbeat_details
        postgres_details = PostgreSQLHeartbeatDetails.from_activity_details(details)
        heartbeat_details.append(postgres_details)

    activity_environment.on_heartbeat = track_heartbeat_details

    insert_inputs = PostgresInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_model=model,
        **postgres_config,
    )

    with unittest.mock.patch(
        "posthog.temporal.common.clickhouse.ClickHouseClient",
        lambda *args, **kwargs: FlakyClickHouseClient(*args, **kwargs, fail_after_records=fail_after_records),
    ):
        # We expect this to raise an exception
        with pytest.raises(RecordBatchTaskError):
            await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    assert len(heartbeat_details) > 0
    detail = heartbeat_details[-1]
    assert len(detail.done_ranges) > 0
    assert detail.records_completed == fail_after_records

    # Now we resume from the heartbeat
    previous_info = dataclasses.asdict(activity_environment.info)
    previous_info["heartbeat_details"] = detail.serialize_details()
    new_info = activity.Info(
        **previous_info,
    )

    activity_environment.info = new_info

    await activity_environment.run(insert_into_postgres_activity, insert_inputs)

    assert len(heartbeat_details) > 0
    detail = heartbeat_details[-1]
    assert len(detail.done_ranges) == 1
    assert detail.done_ranges[0] == (data_interval_start, data_interval_end)

    sort_key = "event" if model.name == "events" else "person_id"

    # Verify all the data for the whole range was exported correctly
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
        sort_key=sort_key,
        expect_duplicates=True,
        primary_key=["uuid"] if model.name == "events" else ["distinct_id", "person_id"],
    )


@pytest.mark.parametrize(
    "input_data, expected_data",
    [
        (b"Hello \uD83D\uDE00 World", b"Hello \uD83D\uDE00 World"),  # Valid emoji pair (😀)
        (b"Bad \uD800 unpaired high", b"Bad  unpaired high"),  # Unpaired high surrogate
        (b"Bad \uDC00 unpaired low", b"Bad  unpaired low"),  # Unpaired low surrogate
        (
            b"\uD83C\uDF89 Party \uD800 \uD83D\uDE0A mixed",
            b"\uD83C\uDF89 Party  \uD83D\uDE0A mixed",
        ),  # Mix of valid pairs and unpaired
        (b"Hello \u0000 World", b"Hello  World"),  # \u0000 is not a valid JSON character in PostgreSQL
        (b"Hello \\u0000 World", b"Hello  World"),  # this is the same as the above
        (b"Hello \\\\u0000 World", b"Hello \\\\u0000 World"),  # \\u0000 is escaped
    ],
)
def test_remove_invalid_json(input_data, expected_data):
    assert remove_invalid_json(input_data) == expected_data

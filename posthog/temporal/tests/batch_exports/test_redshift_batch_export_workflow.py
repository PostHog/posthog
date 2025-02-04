import datetime as dt
import json
import operator
import os
import uuid
import warnings

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
from posthog.temporal.batch_exports.redshift_batch_export import (
    RedshiftBatchExportInputs,
    RedshiftBatchExportWorkflow,
    RedshiftInsertInputs,
    insert_into_redshift_activity,
    redshift_default_fields,
)
from posthog.temporal.batch_exports.temporary_file import (
    remove_escaped_whitespace_recursive,
)
from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.tests.batch_exports.utils import mocked_start_batch_export_run
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

REQUIRED_ENV_VARS = (
    "REDSHIFT_USER",
    "REDSHIFT_PASSWORD",
    "REDSHIFT_HOST",
)

MISSING_REQUIRED_ENV_VARS = any(env_var not in os.environ for env_var in REQUIRED_ENV_VARS)


pytestmark = [pytest.mark.django_db, pytest.mark.asyncio]

EXPECTED_PERSONS_BATCH_EXPORT_FIELDS = [
    "team_id",
    "distinct_id",
    "person_id",
    "properties",
    "person_version",
    "person_distinct_id_version",
    "created_at",
]


async def assert_clickhouse_records_in_redshfit(
    redshift_connection,
    clickhouse_client: ClickHouseClient,
    schema_name: str,
    table_name: str,
    team_id: int,
    batch_export_model: BatchExportModel | BatchExportSchema | None,
    date_ranges: list[tuple[dt.datetime, dt.datetime]],
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    properties_data_type: str = "varchar",
    sort_key: str = "event",
    backfill_details: BackfillDetails | None = None,
    expected_duplicates_threshold: float = 0.0,
    expected_fields: list[str] | None = None,
):
    """Assert expected records are written to a given Redshift table.

    The steps this function takes to assert records are written are:
    1. Read all records inserted into given Redshift table.
    2. Cast records read from Redshift to a Python list of dicts.
    3. Assert records read from Redshift have the expected column names.
    4. Read all records that were supposed to be inserted from ClickHouse.
    5. Cast records returned by ClickHouse to a Python list of dicts.
    6. Compare each record returned by ClickHouse to each record read from Redshift.

    Caveats:
    * Casting records to a Python list of dicts means losing some type precision.
    * Reading records from ClickHouse could be hiding bugs in the `iter_records` function and related.
        * `iter_records` has its own set of related unit tests to control for this.

    Arguments:
        redshift_connection: A Redshift connection used to read inserted events.
        clickhouse_client: A ClickHouseClient used to read events that are expected to be inserted.
        schema_name: Redshift schema name.
        table_name: Redshift table name.
        team_id: The ID of the team that we are testing events for.
        batch_export_schema: Custom schema used in the batch export.
        date_ranges: Ranges of records we should expect to have been exported.
        expected_duplicates_threshold: Threshold of duplicates we should expect relative to
            number of unique events, fail if we exceed it.
        expected_fields: The expected fields to be exported.
    """
    super_columns = ["properties", "set", "set_once", "person_properties"]

    inserted_records = []
    async with redshift_connection.cursor() as cursor:
        await cursor.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(schema_name, table_name)))
        columns = [column.name for column in cursor.description]

        for row in await cursor.fetchall():
            event = dict(zip(columns, row))

            for column in super_columns:
                # When reading a SUPER type field we read it as a str.
                # But Redshift will remove all unquoted whitespace, so
                # '{"prop": 1, "prop": 2}' in CH becomes '{"prop":1,"prop":2}' in Redshift.
                # To make comparison easier we load them as JSON even if we don't have
                # properties_data_type set to SUPER, thus they are both dicts.
                if column in event and event.get(column, None) is not None:
                    event[column] = json.loads(event[column])

            inserted_records.append(event)

    schema_column_names = (
        expected_fields if expected_fields is not None else [field["alias"] for field in redshift_default_fields()]
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
    for data_interval_start, data_interval_end in date_ranges:
        async for record_batch in iter_model_records(
            client=clickhouse_client,
            model=batch_export_model,
            team_id=team_id,
            interval_start=data_interval_start.isoformat(),
            interval_end=data_interval_end.isoformat(),
            exclude_events=exclude_events,
            include_events=include_events,
            destination_default_fields=redshift_default_fields(),
            backfill_details=backfill_details,
            use_latest_schema=True,
        ):
            for record in record_batch.select(schema_column_names).to_pylist():
                expected_record = {}

                for k, v in record.items():
                    if k not in schema_column_names or k == "_inserted_at":
                        # _inserted_at is not exported, only used for tracking progress.
                        continue

                    elif k in super_columns and v is not None:
                        expected_record[k] = remove_escaped_whitespace_recursive(json.loads(v))
                    elif isinstance(v, dt.datetime):
                        expected_record[k] = v.replace(tzinfo=dt.UTC)
                    else:
                        expected_record[k] = v

                expected_records.append(expected_record)

    if expected_duplicates_threshold > 0.0:
        seen = set()

        def is_record_seen(record) -> bool:
            nonlocal seen
            if record["uuid"] in seen:
                return True

            seen.add(record["uuid"])
            return False

        inserted_records = [record for record in inserted_records if not is_record_seen(record)]
        unduplicated_len = len(inserted_records)
        assert (unduplicated_len - len(inserted_records)) / len(inserted_records) < expected_duplicates_threshold

    inserted_column_names = list(inserted_records[0].keys())
    expected_column_names = list(expected_records[0].keys())
    inserted_column_names.sort()
    expected_column_names.sort()

    inserted_records.sort(key=operator.itemgetter(sort_key))
    expected_records.sort(key=operator.itemgetter(sort_key))

    assert inserted_column_names == expected_column_names
    assert inserted_records[0] == expected_records[0]
    assert inserted_records == expected_records
    assert len(inserted_records) == len(expected_records)


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
        # this is needed, otherwise query results are cached
        autocommit=True,
    )
    connection.prepare_threshold = None

    yield connection

    await connection.close()


@pytest.fixture
def properties_data_type(request) -> str:
    """A parametrizable fixture to configure the `str` `properties_data_type` setting."""
    try:
        return request.param
    except AttributeError:
        return "varchar"


TEST_MODELS: list[BatchExportModel | BatchExportSchema | None] = [
    BatchExportModel(
        name="a-custom-model",
        schema={
            "fields": [
                {"expression": "event", "alias": "event"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
            ],
            "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
        },
    ),
    BatchExportModel(name="events", schema=None),
    BatchExportModel(name="persons", schema=None),
    {
        "fields": [
            {"expression": "event", "alias": "event"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
        ],
        "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
    },
    None,
]


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("properties_data_type", ["super", "varchar"], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_insert_into_redshift_activity_inserts_data_into_redshift_table(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    exclude_events,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    properties_data_type,
    ateam,
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
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    if isinstance(model, BatchExportModel) and model.name == "persons" and MISSING_REQUIRED_ENV_VARS:
        pytest.skip("Persons batch export cannot be tested in PostgreSQL")

    if properties_data_type == "super" and MISSING_REQUIRED_ENV_VARS:
        pytest.skip("SUPER type is only available in Redshift")

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        event_name="test-funny-props-{i}",
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10,
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

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    table_name = f"test_insert_activity_table__{ateam.pk}"
    insert_inputs = RedshiftInsertInputs(
        team_id=ateam.pk,
        table_name=table_name,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        properties_data_type=properties_data_type,
        **redshift_config,
    )

    await activity_environment.run(insert_into_redshift_activity, insert_inputs)

    await assert_clickhouse_records_in_redshfit(
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        schema_name=redshift_config["schema"],
        table_name=table_name,
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=model,
        exclude_events=exclude_events,
        properties_data_type=properties_data_type,
        sort_key="person_id" if batch_export_model is not None and batch_export_model.name == "persons" else "event",
    )


@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize(
    "done_relative_ranges,expected_relative_ranges",
    [
        (
            [(dt.timedelta(minutes=0), dt.timedelta(minutes=15))],
            [(dt.timedelta(minutes=15), dt.timedelta(minutes=60))],
        ),
        (
            [
                (dt.timedelta(minutes=10), dt.timedelta(minutes=15)),
                (dt.timedelta(minutes=35), dt.timedelta(minutes=45)),
            ],
            [
                (dt.timedelta(minutes=0), dt.timedelta(minutes=10)),
                (dt.timedelta(minutes=15), dt.timedelta(minutes=35)),
                (dt.timedelta(minutes=45), dt.timedelta(minutes=60)),
            ],
        ),
        (
            [
                (dt.timedelta(minutes=45), dt.timedelta(minutes=60)),
            ],
            [
                (dt.timedelta(minutes=0), dt.timedelta(minutes=45)),
            ],
        ),
    ],
)
async def test_insert_into_bigquery_activity_resumes_from_heartbeat(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    exclude_events,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
    done_relative_ranges,
    expected_relative_ranges,
):
    """Test we insert partial data into a BigQuery table when resuming.

    After an activity runs, heartbeats, and crashes, a follow-up activity should
    pick-up from where the first one left. This capability is critical to ensure
    long-running activities that export a lot of data will eventually finish.
    """
    batch_export_model = BatchExportModel(name="events", schema=None)
    properties_data_type = "varchar"

    insert_inputs = RedshiftInsertInputs(
        team_id=ateam.pk,
        table_name=f"test_insert_activity_table_{ateam.pk}",
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_model=batch_export_model,
        properties_data_type=properties_data_type,
        **redshift_config,
    )

    done_ranges = [
        (
            (data_interval_start + done_relative_range[0]).isoformat(),
            (data_interval_start + done_relative_range[1]).isoformat(),
        )
        for done_relative_range in done_relative_ranges
    ]
    expected_ranges = [
        (
            (data_interval_start + expected_relative_range[0]),
            (data_interval_start + expected_relative_range[1]),
        )
        for expected_relative_range in expected_relative_ranges
    ]
    workflow_id = uuid.uuid4()

    fake_info = activity.Info(
        activity_id="insert-into-redshift-activity",
        activity_type="unknown",
        current_attempt_scheduled_time=dt.datetime.now(dt.UTC),
        workflow_id=str(workflow_id),
        workflow_type="redshift-export",
        workflow_run_id=str(uuid.uuid4()),
        attempt=1,
        heartbeat_timeout=dt.timedelta(seconds=1),
        heartbeat_details=[done_ranges],
        is_local=False,
        schedule_to_close_timeout=dt.timedelta(seconds=10),
        scheduled_time=dt.datetime.now(dt.UTC),
        start_to_close_timeout=dt.timedelta(seconds=20),
        started_time=dt.datetime.now(dt.UTC),
        task_queue="test",
        task_token=b"test",
        workflow_namespace="default",
    )

    activity_environment.info = fake_info
    await activity_environment.run(insert_into_redshift_activity, insert_inputs)

    await assert_clickhouse_records_in_redshfit(
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        schema_name=redshift_config["schema"],
        table_name=f"test_insert_activity_table_{ateam.pk}",
        team_id=ateam.pk,
        date_ranges=expected_ranges,
        batch_export_model=batch_export_model,
        exclude_events=exclude_events,
        properties_data_type=properties_data_type,
        sort_key="event",
        expected_duplicates_threshold=0.1,
    )


async def test_insert_into_redshift_activity_completes_range(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    exclude_events,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test we complete a full range of data into a Redshift table when resuming.

    We run two activities:
    1. First activity, up to (and including) the cutoff event.
    2. Second activity with a heartbeat detail matching the cutoff event.

    This simulates the batch export resuming from a failed execution. The full range
    should be completed (with a duplicate on the cutoff event) after both activities
    are done.
    """
    batch_export_model = BatchExportModel(name="events", schema=None)
    properties_data_type = "varchar"

    events_to_export_created, _ = generate_test_data
    events_to_export_created.sort(key=operator.itemgetter("inserted_at"))

    cutoff_event = events_to_export_created[len(events_to_export_created) // 2 : len(events_to_export_created) // 2 + 1]
    assert len(cutoff_event) == 1
    cutoff_event = cutoff_event[0]
    cutoff_data_interval_end = dt.datetime.fromisoformat(cutoff_event["inserted_at"]).replace(tzinfo=dt.UTC)

    insert_inputs = RedshiftInsertInputs(
        team_id=ateam.pk,
        table_name=f"test_insert_activity_table_{ateam.pk}",
        data_interval_start=data_interval_start.isoformat(),
        # The extra second is because the upper range select is exclusive and
        # we want cutoff to be the last event included.
        data_interval_end=(cutoff_data_interval_end + dt.timedelta(seconds=1)).isoformat(),
        exclude_events=exclude_events,
        batch_export_model=batch_export_model,
        properties_data_type=properties_data_type,
        **redshift_config,
    )

    await activity_environment.run(insert_into_redshift_activity, insert_inputs)

    done_ranges = [
        (
            data_interval_start.isoformat(),
            cutoff_data_interval_end.isoformat(),
        ),
    ]
    workflow_id = uuid.uuid4()

    fake_info = activity.Info(
        activity_id="insert-into-bigquery-activity",
        activity_type="unknown",
        current_attempt_scheduled_time=dt.datetime.now(dt.UTC),
        workflow_id=str(workflow_id),
        workflow_type="bigquery-export",
        workflow_run_id=str(uuid.uuid4()),
        attempt=1,
        heartbeat_timeout=dt.timedelta(seconds=1),
        heartbeat_details=[done_ranges],
        is_local=False,
        schedule_to_close_timeout=dt.timedelta(seconds=10),
        scheduled_time=dt.datetime.now(dt.UTC),
        start_to_close_timeout=dt.timedelta(seconds=20),
        started_time=dt.datetime.now(dt.UTC),
        task_queue="test",
        task_token=b"test",
        workflow_namespace="default",
    )

    activity_environment.info = fake_info

    insert_inputs = RedshiftInsertInputs(
        team_id=ateam.pk,
        table_name=f"test_insert_activity_table_{ateam.pk}",
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        batch_export_model=batch_export_model,
        properties_data_type=properties_data_type,
        **redshift_config,
    )

    await activity_environment.run(insert_into_redshift_activity, insert_inputs)

    await assert_clickhouse_records_in_redshfit(
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        schema_name=redshift_config["schema"],
        table_name=f"test_insert_activity_table_{ateam.pk}",
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=batch_export_model,
        exclude_events=exclude_events,
        properties_data_type=properties_data_type,
        sort_key="event",
        expected_duplicates_threshold=0.1,
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
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_redshift_export_workflow(
    clickhouse_client,
    redshift_config,
    psycopg_connection,
    interval,
    redshift_batch_export,
    ateam,
    exclude_events,
    table_name,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
):
    """Test Redshift Export Workflow end-to-end.

    The workflow should update the batch export run status to completed and produce the expected
    records to the provided Redshift instance.
    """
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    if isinstance(model, BatchExportModel) and model.name == "persons" and MISSING_REQUIRED_ENV_VARS:
        pytest.skip("Persons batch export cannot be tested in PostgreSQL")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    workflow_id = str(uuid.uuid4())
    inputs = RedshiftBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(redshift_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **redshift_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[RedshiftBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_redshift_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with override_settings(BATCH_EXPORT_REDSHIFT_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
                await activity_environment.client.execute_workflow(
                    RedshiftBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=10),
                )

    runs = await afetch_batch_export_runs(batch_export_id=redshift_batch_export.id)
    assert len(runs) == 1

    events_to_export_created, persons_to_export_created = generate_test_data

    run = runs[0]
    assert run.status == "Completed"
    assert run.records_completed == len(events_to_export_created) or run.records_completed == len(
        persons_to_export_created
    )
    await assert_clickhouse_records_in_redshfit(
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        schema_name=redshift_config["schema"],
        table_name=table_name,
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=model,
        exclude_events=exclude_events,
        sort_key="person_id" if batch_export_model is not None and batch_export_model.name == "persons" else "event",
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


async def test_redshift_export_workflow_handles_insert_activity_errors(
    event_loop, ateam, redshift_batch_export, interval
):
    """Test that Redshift Export Workflow can gracefully handle errors when inserting Redshift data."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = RedshiftBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(redshift_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **redshift_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_redshift_activity")
    async def insert_into_redshift_activity_mocked(_: RedshiftInsertInputs) -> str:
        raise ValueError("A useful error message")

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[RedshiftBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_redshift_activity_mocked,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    RedshiftBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=20),
                )

    runs = await afetch_batch_export_runs(batch_export_id=redshift_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "FailedRetryable"
    assert run.latest_error == "ValueError: A useful error message"
    assert run.records_completed is None


async def test_redshift_export_workflow_handles_insert_activity_non_retryable_errors(
    ateam, redshift_batch_export, interval
):
    """Test that Redshift Export Workflow can gracefully handle non-retryable errors when inserting Redshift data."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = RedshiftBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(redshift_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **redshift_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_redshift_activity")
    async def insert_into_redshift_activity_mocked(_: RedshiftInsertInputs) -> str:
        class InsufficientPrivilege(Exception):
            pass

        raise InsufficientPrivilege("A useful error message")

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[RedshiftBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_redshift_activity_mocked,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    RedshiftBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=redshift_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert run.latest_error == "InsufficientPrivilege: A useful error message"
    assert run.records_completed is None


async def test_insert_into_redshift_activity_merges_data_in_follow_up_runs(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    generate_test_persons_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_redshift_activity` merges new versions of rows.

    This unit test looks at the mutability handling capabilities of the aforementioned activity.
    We will generate a new entry in the persons table for half of the persons exported in a first
    run of the activity. We expect the new entries to have replaced the old ones in Redshift after
    the second run.
    """
    if MISSING_REQUIRED_ENV_VARS:
        pytest.skip("Persons batch export cannot be tested in PostgreSQL")

    model = BatchExportModel(name="persons", schema=None)
    properties_data_type = "varchar"

    insert_inputs = RedshiftInsertInputs(
        team_id=ateam.pk,
        table_name=f"test_insert_activity_mutability_table_{ateam.pk}",
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        properties_data_type=properties_data_type,
        **redshift_config,
    )

    await activity_environment.run(insert_into_redshift_activity, insert_inputs)

    await assert_clickhouse_records_in_redshfit(
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        schema_name=redshift_config["schema"],
        table_name=f"test_insert_activity_mutability_table_{ateam.pk}",
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=model,
        properties_data_type=properties_data_type,
        sort_key="person_id",
    )

    persons_to_export_created = generate_test_persons_data

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

    await activity_environment.run(insert_into_redshift_activity, insert_inputs)

    await assert_clickhouse_records_in_redshfit(
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        schema_name=redshift_config["schema"],
        table_name=f"test_insert_activity_mutability_table_{ateam.pk}",
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=model,
        properties_data_type=properties_data_type,
        sort_key="person_id",
    )


async def test_insert_into_redshift_activity_handles_person_schema_changes(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    generate_test_persons_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_redshift_activity` handles changes to the
    person schema.

    If we update the schema of the persons model we export, we should still be
    able to export the data without breaking existing exports. For example, any
    new fields should not be added to the destination (in future we may want to
    allow this but for now we don't).

    To replicate this situation we first export the data with the original
    schema, then delete a column in the destination and then rerun the export.
    """
    if MISSING_REQUIRED_ENV_VARS:
        pytest.skip("Persons batch export cannot be tested in PostgreSQL")

    model = BatchExportModel(name="persons", schema=None)
    properties_data_type = "varchar"

    insert_inputs = RedshiftInsertInputs(
        team_id=ateam.pk,
        table_name=f"test_insert_activity_migration_table__{ateam.pk}",
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        properties_data_type=properties_data_type,
        **redshift_config,
    )

    await activity_environment.run(insert_into_redshift_activity, insert_inputs)

    await assert_clickhouse_records_in_redshfit(
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        schema_name=redshift_config["schema"],
        table_name=f"test_insert_activity_migration_table__{ateam.pk}",
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=model,
        properties_data_type=properties_data_type,
        sort_key="person_id",
    )

    # Drop the created_at column from the Redshift table
    async with psycopg_connection.transaction():
        async with psycopg_connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL("ALTER TABLE {table} DROP COLUMN created_at").format(
                    table=sql.Identifier(redshift_config["schema"], f"test_insert_activity_migration_table__{ateam.pk}")
                )
            )

    persons_to_export_created = generate_test_persons_data

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

    await activity_environment.run(insert_into_redshift_activity, insert_inputs)

    # This time we don't expect there to be a created_at column
    expected_fields = [f for f in EXPECTED_PERSONS_BATCH_EXPORT_FIELDS if f != "created_at"]

    await assert_clickhouse_records_in_redshfit(
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        schema_name=redshift_config["schema"],
        table_name=f"test_insert_activity_migration_table__{ateam.pk}",
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=model,
        properties_data_type=properties_data_type,
        sort_key="person_id",
        expected_fields=expected_fields,
    )

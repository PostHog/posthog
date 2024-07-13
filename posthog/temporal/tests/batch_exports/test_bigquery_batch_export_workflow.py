import asyncio
import datetime as dt
import json
import operator
import os
import typing
import uuid

import pyarrow as pa
import pytest
import pytest_asyncio
from django.conf import settings
from freezegun.api import freeze_time
from google.cloud import bigquery
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.batch_exports.service import BatchExportModel, BatchExportSchema, BigQueryBatchExportInputs
from posthog.temporal.batch_exports.batch_exports import (
    finish_batch_export_run,
    iter_model_records,
    start_batch_export_run,
)
from posthog.temporal.batch_exports.bigquery_batch_export import (
    BigQueryBatchExportWorkflow,
    BigQueryInsertInputs,
    bigquery_default_fields,
    get_bigquery_fields_from_record_schema,
    insert_into_bigquery_activity,
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

SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS = pytest.mark.skipif(
    "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ,
    reason="Google credentials not set in environment",
)

pytestmark = [SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS, pytest.mark.asyncio, pytest.mark.django_db]

TEST_TIME = dt.datetime.now(dt.UTC)


async def assert_clickhouse_records_in_bigquery(
    bigquery_client: bigquery.Client,
    clickhouse_client: ClickHouseClient,
    team_id: int,
    table_id: str,
    dataset_id: str,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    min_ingested_timestamp: dt.datetime,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    batch_export_model: BatchExportModel | BatchExportSchema | None = None,
    use_json_type: bool = False,
    sort_key: str = "event",
    is_backfill: bool = False,
) -> None:
    """Assert ClickHouse records are written to a given BigQuery table.

    Arguments:
        bigquery_connection: A BigQuery connection used to read inserted records.
        clickhouse_client: A ClickHouseClient used to read records that are expected to be exported.
        team_id: The ID of the team that we are testing for.
        table_id: BigQuery table id where records are exported to.
        dataset_id: BigQuery dataset containing the table where records are exported to.
        data_interval_start: Start of the batch period for exported records.
        data_interval_end: End of the batch period for exported records.
        min_ingested_timestamp: A datetime used to assert a minimum bound for 'bq_ingested_timestamp'.
        exclude_events: Event names to be excluded from the export.
        include_events: Event names to be included in the export.
        batch_export_schema: Custom schema used in the batch export.
        use_json_type: Whether to use JSON type for known fields.
    """
    if use_json_type is True:
        json_columns = ["properties", "set", "set_once", "person_properties"]
    else:
        json_columns = []

    query_job = bigquery_client.query(f"SELECT * FROM {dataset_id}.{table_id}")
    result = query_job.result()

    inserted_records = []
    inserted_bq_ingested_timestamp = []

    for row in result:
        inserted_record = {}

        for k, v in row.items():
            if k == "bq_ingested_timestamp":
                inserted_bq_ingested_timestamp.append(v)
                continue

            inserted_record[k] = json.loads(v) if k in json_columns and v is not None else v

        inserted_records.append(inserted_record)

    schema_column_names = [field["alias"] for field in bigquery_default_fields()]
    if batch_export_model is not None:
        if isinstance(batch_export_model, BatchExportModel):
            batch_export_schema = batch_export_model.schema
        else:
            batch_export_schema = batch_export_model

        if batch_export_schema is not None:
            schema_column_names = [field["alias"] for field in batch_export_schema["fields"]]
        elif isinstance(batch_export_model, BatchExportModel) and batch_export_model.name == "persons":
            schema_column_names = [
                "team_id",
                "distinct_id",
                "person_id",
                "properties",
                "person_version",
                "person_distinct_id_version",
                "_inserted_at",
            ]

    expected_records = []
    async for record_batch in iter_model_records(
        client=clickhouse_client,
        model=batch_export_model,
        team_id=team_id,
        interval_start=data_interval_start.isoformat(),
        interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        include_events=include_events,
        destination_default_fields=bigquery_default_fields(),
        is_backfill=is_backfill,
    ):
        for record in record_batch.select(schema_column_names).to_pylist():
            expected_record = {}

            for k, v in record.items():
                if k not in schema_column_names or k == "_inserted_at" or k == "bq_ingested_timestamp":
                    # _inserted_at is not exported, only used for tracking progress.
                    # bq_ingested_timestamp cannot be compared as it comes from an unstable function.
                    continue

                if k in json_columns and v is not None:
                    expected_record[k] = json.loads(v)
                elif isinstance(v, dt.datetime):
                    expected_record[k] = v.replace(tzinfo=dt.UTC)
                else:
                    expected_record[k] = v

            expected_records.append(expected_record)

    assert len(inserted_records) == len(expected_records)

    # Ordering is not guaranteed, so we sort before comparing.
    inserted_records.sort(key=operator.itemgetter(sort_key))
    expected_records.sort(key=operator.itemgetter(sort_key))

    if "team_id" in schema_column_names:
        assert all(record["team_id"] == team_id for record in inserted_records)

    assert inserted_records[0] == expected_records[0]
    assert inserted_records == expected_records

    if len(inserted_bq_ingested_timestamp) > 0:
        assert all(ts >= min_ingested_timestamp for ts in inserted_bq_ingested_timestamp)


@pytest.fixture
def bigquery_config() -> dict[str, str]:
    """Return a BigQuery configuration dictionary to use in tests."""
    credentials_file_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open(credentials_file_path) as f:
        credentials = json.load(f)

    return {
        "project_id": credentials["project_id"],
        "private_key": credentials["private_key"],
        "private_key_id": credentials["private_key_id"],
        "token_uri": credentials["token_uri"],
        "client_email": credentials["client_email"],
    }


@pytest.fixture
def bigquery_client() -> typing.Generator[bigquery.Client, None, None]:
    """Manage a bigquery.Client for testing."""
    client = bigquery.Client()

    yield client

    client.close()


@pytest.fixture
def bigquery_dataset(bigquery_config, bigquery_client) -> typing.Generator[bigquery.Dataset, None, None]:
    """Manage a bigquery dataset for testing.

    We clean up the dataset after every test. Could be quite time expensive, but guarantees a clean slate.
    """
    dataset_id = f"{bigquery_config['project_id']}.BatchExportsTest_{str(uuid.uuid4()).replace('-', '')}"

    dataset = bigquery.Dataset(dataset_id)
    dataset = bigquery_client.create_dataset(dataset)

    yield dataset

    # bigquery_client.delete_dataset(dataset_id, delete_contents=True, not_found_ok=True)


@pytest.fixture
def use_json_type(request) -> bool:
    """A parametrizable fixture to configure the bool use_json_type setting."""
    try:
        return request.param
    except AttributeError:
        return False


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
@pytest.mark.parametrize("use_json_type", [False, True], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_insert_into_bigquery_activity_inserts_data_into_bigquery_table(
    clickhouse_client,
    activity_environment,
    bigquery_client,
    bigquery_config,
    exclude_events,
    bigquery_dataset,
    use_json_type,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_bigquery_activity` function inserts data into a BigQuery table.

    We use the `generate_test_data` fixture function to generate several sets
    of events. Some of these sets are expected to be exported, and others not. Expected
    events are those that:
    * Are created for the `team_id` of the batch export.
    * Are created in the date range of the batch export.
    * Are not duplicates of other events that are in the same batch.
    * Do not have an event name contained in the batch export's `exclude_events`.
    """
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    insert_inputs = BigQueryInsertInputs(
        team_id=ateam.pk,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        use_json_type=use_json_type,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **bigquery_config,
    )

    with freeze_time(TEST_TIME) as frozen_time:
        await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

        ingested_timestamp = frozen_time().replace(tzinfo=dt.UTC)

        await assert_clickhouse_records_in_bigquery(
            bigquery_client=bigquery_client,
            clickhouse_client=clickhouse_client,
            table_id=f"test_insert_activity_table_{ateam.pk}",
            dataset_id=bigquery_dataset.dataset_id,
            team_id=ateam.pk,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            exclude_events=exclude_events,
            include_events=None,
            batch_export_model=model,
            use_json_type=use_json_type,
            min_ingested_timestamp=ingested_timestamp,
            sort_key="person_id"
            if batch_export_model is not None and batch_export_model.name == "persons"
            else "event",
        )


async def test_insert_into_bigquery_activity_merges_data_in_follow_up_runs(
    clickhouse_client,
    activity_environment,
    bigquery_client,
    bigquery_config,
    bigquery_dataset,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_bigquery_activity` merges new versions of rows.

    This unit tests looks at the mutability handling capabilities of the aforementioned activity.
    We will generate a new entry in the persons table for half of the persons exported in a first
    run of the activity. We expect the new entries to have replaced the old ones in BigQuery after
    the second run.
    """
    model = BatchExportModel(name="persons", schema=None)

    insert_inputs = BigQueryInsertInputs(
        team_id=ateam.pk,
        table_id=f"test_insert_activity_mutability_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        **bigquery_config,
    )

    with freeze_time(TEST_TIME) as frozen_time:
        await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

        ingested_timestamp = frozen_time().replace(tzinfo=dt.UTC)

        await assert_clickhouse_records_in_bigquery(
            bigquery_client=bigquery_client,
            clickhouse_client=clickhouse_client,
            table_id=f"test_insert_activity_mutability_table_{ateam.pk}",
            dataset_id=bigquery_dataset.dataset_id,
            team_id=ateam.pk,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            batch_export_model=model,
            min_ingested_timestamp=ingested_timestamp,
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

    with freeze_time(TEST_TIME) as frozen_time:
        await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

        ingested_timestamp = frozen_time().replace(tzinfo=dt.UTC)

        await assert_clickhouse_records_in_bigquery(
            bigquery_client=bigquery_client,
            clickhouse_client=clickhouse_client,
            table_id=f"test_insert_activity_mutability_table_{ateam.pk}",
            dataset_id=bigquery_dataset.dataset_id,
            team_id=ateam.pk,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            batch_export_model=model,
            min_ingested_timestamp=ingested_timestamp,
            sort_key="person_id",
        )


@pytest.fixture
def table_id(ateam, interval):
    return f"test_workflow_table_{ateam.pk}_{interval}"


@pytest_asyncio.fixture
async def bigquery_batch_export(
    ateam, table_id, bigquery_config, interval, exclude_events, use_json_type, temporal_client, bigquery_dataset
):
    destination_data = {
        "type": "BigQuery",
        "config": {
            **bigquery_config,
            "table_id": table_id,
            "dataset_id": bigquery_dataset.dataset_id,
            "exclude_events": exclude_events,
            "use_json_type": use_json_type,
        },
    }

    batch_export_data = {
        "name": "my-production-bigquery-destination",
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


@pytest.mark.parametrize("interval", ["hour", "day"])
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("use_json_type", [False, True], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_bigquery_export_workflow(
    clickhouse_client,
    bigquery_client,
    bigquery_batch_export,
    interval,
    exclude_events,
    ateam,
    table_id,
    use_json_type,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
):
    """Test BigQuery Export Workflow end-to-end.

    The workflow should update the batch export run status to completed and produce the expected
    records to the configured BigQuery table.
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
    inputs = BigQueryBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(bigquery_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **bigquery_batch_export.destination.config,
    )

    with freeze_time(TEST_TIME) as frozen_time:
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                workflows=[BigQueryBatchExportWorkflow],
                activities=[
                    start_batch_export_run,
                    insert_into_bigquery_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await activity_environment.client.execute_workflow(
                    BigQueryBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=10),
                )

        runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
        assert len(runs) == 1

        events_to_export_created, persons_to_export_created = generate_test_data
        run = runs[0]
        assert run.status == "Completed"
        assert run.records_completed == len(events_to_export_created) or run.records_completed == len(
            persons_to_export_created
        )

        ingested_timestamp = frozen_time().replace(tzinfo=dt.UTC)
        await assert_clickhouse_records_in_bigquery(
            bigquery_client=bigquery_client,
            clickhouse_client=clickhouse_client,
            table_id=table_id,
            dataset_id=bigquery_batch_export.destination.config["dataset_id"],
            team_id=ateam.pk,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            exclude_events=exclude_events,
            include_events=None,
            batch_export_model=model,
            use_json_type=use_json_type,
            min_ingested_timestamp=ingested_timestamp,
            sort_key="person_id"
            if batch_export_model is not None and batch_export_model.name == "persons"
            else "event",
        )


@pytest.mark.parametrize("interval", ["hour"])
@pytest.mark.parametrize("exclude_events", [None], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_bigquery_export_workflow_without_events(
    clickhouse_client,
    bigquery_batch_export,
    interval,
    exclude_events,
    ateam,
    table_id,
    use_json_type,
    model: BatchExportModel | BatchExportSchema | None,
    data_interval_start,
    data_interval_end,
):
    """Test the BigQuery Export Workflow without any events to export.

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
    inputs = BigQueryBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(bigquery_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **bigquery_batch_export.destination.config,
    )

    with freeze_time(TEST_TIME):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                workflows=[BigQueryBatchExportWorkflow],
                activities=[
                    start_batch_export_run,
                    insert_into_bigquery_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await activity_environment.client.execute_workflow(
                    BigQueryBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=10),
                )

        runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
        assert len(runs) == 1

        run = runs[0]
        assert run.status == "Completed"
        assert run.records_completed == 0


async def test_bigquery_export_workflow_handles_insert_activity_errors(ateam, bigquery_batch_export, interval):
    """Test that BigQuery Export Workflow can gracefully handle errors when inserting BigQuery data."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = BigQueryBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(bigquery_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **bigquery_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_bigquery_activity")
    async def insert_into_bigquery_activity_mocked(_: BigQueryInsertInputs) -> str:
        raise ValueError("A useful error message")

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[BigQueryBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_bigquery_activity_mocked,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    BigQueryBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert run.latest_error == "ValueError: A useful error message"


async def test_bigquery_export_workflow_handles_insert_activity_non_retryable_errors(
    ateam, bigquery_batch_export, interval
):
    """Test that BigQuery Export Workflow can gracefully handle non-retryable errors when inserting BigQuery data."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = BigQueryBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(bigquery_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **bigquery_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_bigquery_activity")
    async def insert_into_bigquery_activity_mocked(_: BigQueryInsertInputs) -> str:
        class RefreshError(Exception):
            pass

        raise RefreshError("A useful error message")

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[BigQueryBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_bigquery_activity_mocked,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    BigQueryBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert run.latest_error == "RefreshError: A useful error message"
    assert run.records_completed is None


async def test_bigquery_export_workflow_handles_cancellation(ateam, bigquery_batch_export, interval):
    """Test that BigQuery Export Workflow can gracefully handle cancellations when inserting BigQuery data."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = BigQueryBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(bigquery_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **bigquery_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_bigquery_activity")
    async def never_finish_activity(_: BigQueryInsertInputs) -> str:
        while True:
            activity.heartbeat()
            await asyncio.sleep(1)

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[BigQueryBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                never_finish_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await activity_environment.client.start_workflow(
                BigQueryBatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            await asyncio.sleep(5)
            await handle.cancel()

            with pytest.raises(WorkflowFailureError):
                await handle.result()

    runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Cancelled"
    assert run.latest_error == "Cancelled"


@pytest.mark.parametrize(
    "pyrecords,expected_schema",
    [
        ([{"test": 1}], [bigquery.SchemaField("test", "INT64")]),
        ([{"test": "a string"}], [bigquery.SchemaField("test", "STRING")]),
        ([{"test": b"a bytes"}], [bigquery.SchemaField("test", "BYTES")]),
        ([{"test": 6.0}], [bigquery.SchemaField("test", "FLOAT64")]),
        ([{"test": True}], [bigquery.SchemaField("test", "BOOL")]),
        ([{"test": dt.datetime.now()}], [bigquery.SchemaField("test", "TIMESTAMP")]),
        ([{"test": dt.datetime.now(tz=dt.UTC)}], [bigquery.SchemaField("test", "TIMESTAMP")]),
        (
            [
                {
                    "test_int": 1,
                    "test_str": "a string",
                    "test_bytes": b"a bytes",
                    "test_float": 6.0,
                    "test_bool": False,
                    "test_timestamp": dt.datetime.now(),
                    "test_timestamptz": dt.datetime.now(tz=dt.UTC),
                }
            ],
            [
                bigquery.SchemaField("test_int", "INT64"),
                bigquery.SchemaField("test_str", "STRING"),
                bigquery.SchemaField("test_bytes", "BYTES"),
                bigquery.SchemaField("test_float", "FLOAT64"),
                bigquery.SchemaField("test_bool", "BOOL"),
                bigquery.SchemaField("test_timestamp", "TIMESTAMP"),
                bigquery.SchemaField("test_timestamptz", "TIMESTAMP"),
            ],
        ),
    ],
)
def test_get_bigquery_fields_from_record_schema(pyrecords, expected_schema):
    """Test BigQuery schema fields generated from record match expected."""
    record_batch = pa.RecordBatch.from_pylist(pyrecords)
    schema = get_bigquery_fields_from_record_schema(record_batch.schema, known_json_columns=[])

    assert schema == expected_schema

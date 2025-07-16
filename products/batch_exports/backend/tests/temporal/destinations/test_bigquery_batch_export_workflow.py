import asyncio
import dataclasses
import datetime as dt
import json
import operator
import os
import typing
import unittest.mock
import uuid
import warnings

import pyarrow as pa
import pytest
import pytest_asyncio
from django.test import override_settings
from google.cloud import bigquery
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.batch_exports.service import (
    BackfillDetails,
    BatchExportModel,
    BatchExportSchema,
    BigQueryBatchExportInputs,
)
from posthog.constants import BATCH_EXPORTS_TASK_QUEUE
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
from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    BigQueryBatchExportWorkflow,
    BigQueryHeartbeatDetails,
    BigQueryInsertInputs,
    bigquery_default_fields,
    get_bigquery_fields_from_record_schema,
    insert_into_bigquery_activity,
)
from products.batch_exports.backend.temporal.record_batch_model import SessionsRecordBatchModel
from products.batch_exports.backend.temporal.spmc import (
    Producer,
    RecordBatchQueue,
    RecordBatchTaskError,
)
from products.batch_exports.backend.tests.temporal.utils import (
    FlakyClickHouseClient,
    get_record_batch_from_queue,
    mocked_start_batch_export_run,
)

SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS = pytest.mark.skipif(
    "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ,
    reason="Google credentials not set in environment",
)

pytestmark = [SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS, pytest.mark.asyncio, pytest.mark.django_db]

TEST_TIME = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)

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


@pytest.fixture
def activity_environment(activity_environment):
    activity_environment.heartbeat_class = BigQueryHeartbeatDetails
    return activity_environment


async def assert_clickhouse_records_in_bigquery(
    bigquery_client: bigquery.Client,
    clickhouse_client: ClickHouseClient,
    team_id: int,
    table_id: str,
    dataset_id: str,
    date_ranges: list[tuple[dt.datetime, dt.datetime]],
    min_ingested_timestamp: dt.datetime | None = None,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    batch_export_model: BatchExportModel | BatchExportSchema | None = None,
    use_json_type: bool = False,
    sort_key: str = "event",
    backfill_details: BackfillDetails | None = None,
    expect_duplicates: bool = False,
    expected_fields: list[str] | None = None,
) -> None:
    """Assert ClickHouse records are written to a given BigQuery table.

    Arguments:
        bigquery_connection: A BigQuery connection used to read inserted records.
        clickhouse_client: A ClickHouseClient used to read records that are expected to be exported.
        team_id: The ID of the team that we are testing for.
        table_id: BigQuery table id where records are exported to.
        dataset_id: BigQuery dataset containing the table where records are exported to.
        date_ranges: Ranges of records we should expect to have been exported.
        min_ingested_timestamp: A datetime used to assert a minimum bound for 'bq_ingested_timestamp'.
        exclude_events: Event names to be excluded from the export.
        include_events: Event names to be included in the export.
        batch_export_schema: Custom schema used in the batch export.
        use_json_type: Whether to use JSON type for known fields.
        expect_duplicates: Whether duplicates are expected (e.g. when testing retrying logic).
        expected_fields: The expected fields to be exported.
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

            if k in json_columns:
                assert (
                    isinstance(v, dict) or v is None
                ), f"Expected '{k}' to be JSON, but it was not deserialized to dict"

            inserted_record[k] = v

        inserted_records.append(inserted_record)

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

    for data_interval_start, data_interval_end in date_ranges:
        producer_task = await producer.start(
            queue=queue,
            model_name=model_name,
            team_id=team_id,
            full_range=(data_interval_start, data_interval_end),
            done_ranges=[],
            fields=fields,
            filters=filters,
            destination_default_fields=bigquery_default_fields(),
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

                    if k in json_columns and v is not None:
                        # We remove unpaired surrogates in BigQuery, so we have to remove them here to so
                        # that comparison doesn't fail. The problem is that at some point our unpaired surrogate gets
                        # escaped (which is correct, as unpaired surrogates are not valid). But then the
                        # comparison fails as in BigQuery we remove unpaired surrogates, not just escape them.
                        # So, we hardcode replace the test properties. Not ideal, but this works as we get the
                        # expected result in BigQuery and the comparison is still useful.
                        v = v.replace("\\ud83e\\udd23\\udd23", "\\ud83e\\udd23").replace(
                            "\\ud83e\\udd23\\ud83e", "\\ud83e\\udd23"
                        )
                        expected_record[k] = json.loads(v)
                    elif isinstance(v, dt.datetime):
                        expected_record[k] = v.replace(tzinfo=dt.UTC)
                    else:
                        expected_record[k] = v

                expected_records.append(expected_record)

    if expect_duplicates:
        seen = set()

        def is_record_seen(record) -> bool:
            nonlocal seen

            if record["uuid"] in seen:
                return True

            seen.add(record["uuid"])
            return False

        inserted_records = [record for record in inserted_records if not is_record_seen(record)]

    assert len(inserted_records) == len(expected_records)

    # Ordering is not guaranteed, so we sort before comparing.
    inserted_records.sort(key=operator.itemgetter(sort_key))
    expected_records.sort(key=operator.itemgetter(sort_key))

    if len(inserted_records) >= 1 and "team_id" in inserted_records[0]:
        assert all(record["team_id"] == team_id for record in inserted_records)

    assert inserted_records[0] == expected_records[0]
    assert inserted_records == expected_records

    if len(inserted_bq_ingested_timestamp) > 0:
        assert (
            min_ingested_timestamp is not None
        ), "Must set `min_ingested_timestamp` for comparison with exported value"
        assert all(ts >= min_ingested_timestamp for ts in inserted_bq_ingested_timestamp)


def drop_column_from_bigquery_table(
    bigquery_client: bigquery.Client, dataset_id: str, table_id: str, column_name: str
) -> None:
    """Drop a column from a BigQuery table."""

    query_job = bigquery_client.query(f"ALTER TABLE {dataset_id}.{table_id} DROP COLUMN {column_name}")
    _ = query_job.result()


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

    try:
        bigquery_client.delete_dataset(dataset_id, delete_contents=True, not_found_ok=True)
    except Exception as exc:
        warnings.warn(
            f"Failed to clean up dataset: {dataset_id} due to '{exc.__class__.__name__}': {str(exc)}", stacklevel=1
        )


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
@pytest.mark.parametrize(
    "test_properties",
    [
        {
            "$browser": "Chrome",
            "$os": "Mac OS X",
            "emoji": "🤣",
            "newline": "\n",
            "emoji_with_high_surrogate": "🤣\ud83e",
            "emoji_with_low_surrogate": "🤣\udd23",
            "emoji_with_high_surrogate_and_newline": "🤣\ud83e\n",
            "emoji_with_low_surrogate_and_newline": "🤣\udd23\n",
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    "test_person_properties",
    [
        {
            "utm_medium": "referral",
            "$initial_os": "Linux",
            "emoji": "🤣",
            "newline": "\n",
            "emoji_with_high_surrogate": "🤣\ud83e",
            "emoji_with_low_surrogate": "🤣\udd23",
            "emoji_with_high_surrogate_and_newline": "🤣\ud83e\n",
            "emoji_with_low_surrogate_and_newline": "🤣\udd23\n",
        }
    ],
    indirect=True,
)
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

    sort_key = "event"
    if batch_export_model is not None:
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

    with override_settings(BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES=1):
        await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

        await assert_clickhouse_records_in_bigquery(
            bigquery_client=bigquery_client,
            clickhouse_client=clickhouse_client,
            table_id=f"test_insert_activity_table_{ateam.pk}",
            dataset_id=bigquery_dataset.dataset_id,
            team_id=ateam.pk,
            date_ranges=[(data_interval_start, data_interval_end)],
            exclude_events=exclude_events,
            include_events=None,
            batch_export_model=model,
            use_json_type=use_json_type,
            min_ingested_timestamp=TEST_TIME,
            sort_key=sort_key,
        )


@pytest.mark.parametrize(
    "model",
    [
        BatchExportModel(name="sessions", schema=None),
    ],
)
async def test_insert_into_bigquery_activity_inserts_sessions_data_into_bigquery_table(
    clickhouse_client,
    activity_environment,
    bigquery_client,
    bigquery_config,
    exclude_events,
    bigquery_dataset,
    use_json_type,
    model: BatchExportModel,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    ateam,
):
    """Test that the `insert_into_bigquery_activity` function inserts sessions data into a BigQuery table.

    This test is the same as the previous one, but we require non-messed up properties to create the
    test session data, so we isolate this model in its own test.

    We use the `generate_test_data` fixture function to generate several sets
    of events. Some of these sets are expected to be exported, and others not. Expected
    events are those that:
    * Are created for the `team_id` of the batch export.
    * Are created in the date range of the batch export.
    * Are not duplicates of other events that are in the same batch.
    * Do not have an event name contained in the batch export's `exclude_events`.
    """
    batch_export_model = model
    insert_inputs = BigQueryInsertInputs(
        team_id=ateam.pk,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        use_json_type=use_json_type,
        batch_export_schema=None,
        batch_export_model=batch_export_model,
        **bigquery_config,
    )

    sort_key = "session_id"

    with override_settings(BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES=1):
        records_completed = await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

        assert records_completed == 1

        await assert_clickhouse_records_in_bigquery(
            bigquery_client=bigquery_client,
            clickhouse_client=clickhouse_client,
            table_id=f"test_insert_activity_table_{ateam.pk}",
            dataset_id=bigquery_dataset.dataset_id,
            team_id=ateam.pk,
            date_ranges=[(data_interval_start, data_interval_end)],
            exclude_events=exclude_events,
            include_events=None,
            batch_export_model=model,
            use_json_type=use_json_type,
            min_ingested_timestamp=TEST_TIME,
            sort_key=sort_key,
        )


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("use_json_type", [False, True], indirect=True)
@pytest.mark.parametrize(
    "model",
    [
        BatchExportModel(
            name="events",
            schema=None,
            filters=[
                {"key": "$browser", "operator": "exact", "type": "event", "value": ["Chrome"]},
                {"key": "$os", "operator": "exact", "type": "event", "value": ["Mac OS X"]},
            ],
        ),
    ],
)
@pytest.mark.parametrize(
    "test_properties",
    [
        {
            "$browser": "Chrome",
            "$os": "Mac OS X",
            "emoji": "🤣",
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    "test_person_properties",
    [
        {
            "utm_medium": "referral",
            "$initial_os": "Linux",
            "emoji": "🤣",
            "newline": "\n",
            "emoji_with_high_surrogate": "🤣\ud83e",
            "emoji_with_low_surrogate": "🤣\udd23",
            "emoji_with_high_surrogate_and_newline": "🤣\ud83e\n",
            "emoji_with_low_surrogate_and_newline": "🤣\udd23\n",
        }
    ],
    indirect=True,
)
async def test_insert_into_bigquery_activity_inserts_data_into_bigquery_table_with_property_filters(
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

    This test exclusively covers a model with property filters as property filters require
    a valid JSON. And the other test uses an invalid JSON due to unpaired surrogates.

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

    with override_settings(BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES=1):
        await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

        await assert_clickhouse_records_in_bigquery(
            bigquery_client=bigquery_client,
            clickhouse_client=clickhouse_client,
            table_id=f"test_insert_activity_table_{ateam.pk}",
            dataset_id=bigquery_dataset.dataset_id,
            team_id=ateam.pk,
            date_ranges=[(data_interval_start, data_interval_end)],
            exclude_events=exclude_events,
            include_events=None,
            batch_export_model=model,
            use_json_type=use_json_type,
            min_ingested_timestamp=TEST_TIME,
            sort_key="event",
        )


@pytest.mark.parametrize("use_json_type", [True], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_insert_into_bigquery_activity_inserts_data_into_bigquery_table_without_query_permissions(
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

    For this test we mock the `acheck_for_query_permissions_on_table` method to assert the
    behavior of the activity function when lacking query permissions in BigQuery.
    """
    if isinstance(model, BatchExportModel) and model.name == "persons":
        pytest.skip("Unnecessary test case as person batch export requires query permissions")

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

    with (
        override_settings(BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES=1),
        unittest.mock.patch(
            "products.batch_exports.backend.temporal.destinations.bigquery_batch_export.BigQueryClient.acheck_for_query_permissions_on_table",
            return_value=False,
        ) as mocked_check,
    ):
        await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

        mocked_check.assert_called_once()
        await assert_clickhouse_records_in_bigquery(
            bigquery_client=bigquery_client,
            clickhouse_client=clickhouse_client,
            table_id=f"test_insert_activity_table_{ateam.pk}",
            dataset_id=bigquery_dataset.dataset_id,
            team_id=ateam.pk,
            date_ranges=[(data_interval_start, data_interval_end)],
            exclude_events=exclude_events,
            include_events=None,
            batch_export_model=model,
            use_json_type=use_json_type,
            min_ingested_timestamp=TEST_TIME,
            sort_key="person_id"
            if batch_export_model is not None and batch_export_model.name == "persons"
            else "event",
        )


async def test_insert_into_bigquery_activity_merges_persons_data_in_follow_up_runs(
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
    table_id = f"test_insert_activity_mutability_table_persons_{ateam.pk}"

    insert_inputs = BigQueryInsertInputs(
        team_id=ateam.pk,
        table_id=table_id,
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        **bigquery_config,
    )

    with override_settings(BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES=1):
        await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

        await assert_clickhouse_records_in_bigquery(
            bigquery_client=bigquery_client,
            clickhouse_client=clickhouse_client,
            table_id=table_id,
            dataset_id=bigquery_dataset.dataset_id,
            team_id=ateam.pk,
            date_ranges=[(data_interval_start, data_interval_end)],
            batch_export_model=model,
            min_ingested_timestamp=TEST_TIME,
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

    await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

    await assert_clickhouse_records_in_bigquery(
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        table_id=table_id,
        dataset_id=bigquery_dataset.dataset_id,
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=model,
        min_ingested_timestamp=TEST_TIME,
        sort_key="person_id",
    )


async def test_insert_into_bigquery_activity_merges_sessions_data_in_follow_up_runs(
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
    We will generate a new entry in the raw_sessions table for the one session exported in the first
    run of the activity. We expect the new entries to have replaced the old ones in BigQuery after
    the second run with the same time range.
    """
    model = BatchExportModel(name="sessions", schema=None)
    table_id = f"test_insert_activity_mutability_table_sessions_{ateam.pk}"

    insert_inputs = BigQueryInsertInputs(
        team_id=ateam.pk,
        table_id=table_id,
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        **bigquery_config,
    )

    records_completed = await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

    assert records_completed == 1

    await assert_clickhouse_records_in_bigquery(
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        table_id=table_id,
        dataset_id=bigquery_dataset.dataset_id,
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=model,
        min_ingested_timestamp=TEST_TIME,
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

    records_completed = await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

    assert records_completed == 1

    await assert_clickhouse_records_in_bigquery(
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        table_id=table_id,
        dataset_id=bigquery_dataset.dataset_id,
        team_id=ateam.pk,
        date_ranges=[(new_data_interval_start, new_data_interval_end)],
        batch_export_model=model,
        min_ingested_timestamp=TEST_TIME,
        sort_key="session_id",
    )

    query_job = bigquery_client.query(f"SELECT * FROM {bigquery_dataset.dataset_id}.{table_id}")
    result = query_job.result()
    rows = list(result)
    new_event = new_events[0]
    new_event_properties = new_event["properties"] or {}
    assert len(rows) == 1
    assert rows[0]["session_id"] == new_event_properties["$session_id"]
    assert rows[0]["end_timestamp"] == dt.datetime.fromisoformat(new_event["timestamp"]).replace(tzinfo=dt.UTC)


async def test_insert_into_bigquery_activity_handles_person_schema_changes(
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
    """Test that the `insert_into_bigquery_activity` handles changes to the
    person schema.

    If we update the schema of the persons model we export, we should still be
    able to export the data without breaking existing exports. For example, any
    new fields should not be added to the destination (in future we may want to
    allow this but for now we don't).

    To replicate this situation we first export the data with the original
    schema, then delete a column in the destination and then rerun the export.
    """
    model = BatchExportModel(name="persons", schema=None)

    insert_inputs = BigQueryInsertInputs(
        team_id=ateam.pk,
        table_id=f"test_insert_activity_migration_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=model,
        **bigquery_config,
    )

    await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

    await assert_clickhouse_records_in_bigquery(
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        table_id=f"test_insert_activity_migration_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=model,
        min_ingested_timestamp=TEST_TIME,
        sort_key="person_id",
    )

    # drop the created_at column from the BigQuery table
    drop_column_from_bigquery_table(
        bigquery_client=bigquery_client,
        dataset_id=bigquery_dataset.dataset_id,
        table_id=f"test_insert_activity_migration_table_{ateam.pk}",
        column_name="created_at",
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

    await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

    # this time we don't expected there to be a created_at column
    expected_fields = [field for field in EXPECTED_PERSONS_BATCH_EXPORT_FIELDS if field != "created_at"]
    await assert_clickhouse_records_in_bigquery(
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        table_id=f"test_insert_activity_migration_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=model,
        min_ingested_timestamp=TEST_TIME,
        sort_key="person_id",
        expected_fields=expected_fields,
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
    bigquery_client,
    bigquery_config,
    bigquery_dataset,
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

    insert_inputs = BigQueryInsertInputs(
        team_id=ateam.pk,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        use_json_type=True,
        batch_export_model=batch_export_model,
        **bigquery_config,
    )

    now = dt.datetime.now(tz=dt.UTC)
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
    await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

    await assert_clickhouse_records_in_bigquery(
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        team_id=ateam.pk,
        date_ranges=expected_ranges,
        include_events=None,
        batch_export_model=batch_export_model,
        use_json_type=True,
        min_ingested_timestamp=now,
        sort_key="event",
    )


async def test_insert_into_bigquery_activity_completes_range(
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
    """Test we complete a full range of data into a BigQuery table when resuming.

    We run two activities:
    1. First activity, up to (and including) the cutoff event.
    2. Second activity with a heartbeat detail matching the cutoff event.

    This simulates the batch export resuming from a failed execution. The full range
    should be completed (with a duplicate on the cutoff event) after both activities
    are done.
    """
    batch_export_model = BatchExportModel(name="events", schema=None)
    now = dt.datetime.now(tz=dt.UTC)

    events_to_export_created, _ = generate_test_data
    events_to_export_created.sort(key=operator.itemgetter("inserted_at"))

    cutoff_event = events_to_export_created[len(events_to_export_created) // 2 : len(events_to_export_created) // 2 + 1]
    assert len(cutoff_event) == 1
    cutoff_event = cutoff_event[0]
    cutoff_data_interval_end = dt.datetime.fromisoformat(cutoff_event["inserted_at"]).replace(tzinfo=dt.UTC)

    insert_inputs = BigQueryInsertInputs(
        team_id=ateam.pk,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        # The extra second is because the upper range select is exclusive and
        # we want cutoff to be the last event included.
        data_interval_end=(cutoff_data_interval_end + dt.timedelta(seconds=1)).isoformat(),
        use_json_type=True,
        batch_export_model=batch_export_model,
        **bigquery_config,
    )

    await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

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

    insert_inputs = BigQueryInsertInputs(
        team_id=ateam.pk,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        use_json_type=True,
        batch_export_model=batch_export_model,
        **bigquery_config,
    )

    await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

    await assert_clickhouse_records_in_bigquery(
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        include_events=None,
        batch_export_model=batch_export_model,
        use_json_type=True,
        min_ingested_timestamp=now,
        sort_key="event",
        expect_duplicates=True,
    )


async def test_insert_into_bigquery_activity_completes_range_when_there_is_a_failure(
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
    """Test that if the insert_into_bigquery_activity activity fails, it can resume from a heartbeat.

    We simulate a failure in the SPMC producer halfway through streaming records, then resume from the heartbeat.
    We're particularly interested in ensuring all records are exported into the final BigQuery table.
    """

    batch_export_model = BatchExportModel(name="events", schema=None)
    now = dt.datetime.now(tz=dt.UTC)
    fail_after_records = 200

    heartbeat_details: list[BigQueryHeartbeatDetails] = []

    def track_hearbeat_details(*details):
        """Record heartbeat details received."""
        nonlocal heartbeat_details
        bigquery_details = BigQueryHeartbeatDetails.from_activity_details(details)
        heartbeat_details.append(bigquery_details)

    activity_environment.on_heartbeat = track_hearbeat_details

    insert_inputs = BigQueryInsertInputs(
        team_id=ateam.pk,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        use_json_type=True,
        batch_export_model=batch_export_model,
        **bigquery_config,
    )

    with unittest.mock.patch(
        "posthog.temporal.common.clickhouse.ClickHouseClient",
        lambda *args, **kwargs: FlakyClickHouseClient(*args, **kwargs, fail_after_records=fail_after_records),
    ):
        # we expect this to raise an exception
        with pytest.raises(RecordBatchTaskError):
            await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

    assert len(heartbeat_details) > 0
    detail = heartbeat_details[-1]
    assert len(detail.done_ranges) > 0
    assert detail.records_completed == fail_after_records

    # now we resume from the heartbeat
    previous_info = dataclasses.asdict(activity_environment.info)
    previous_info["heartbeat_details"] = detail.serialize_details()
    new_info = activity.Info(
        **previous_info,
    )

    activity_environment.info = new_info

    await activity_environment.run(insert_into_bigquery_activity, insert_inputs)

    assert len(heartbeat_details) > 0
    detail = heartbeat_details[-1]
    assert len(detail.done_ranges) == 1
    assert detail.done_ranges[0] == (data_interval_start, data_interval_end)

    # records_completed is actually larger than num_expected_records because of duplicates
    # assert detail.records_completed == num_expected_records

    await assert_clickhouse_records_in_bigquery(
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        table_id=f"test_insert_activity_table_{ateam.pk}",
        dataset_id=bigquery_dataset.dataset_id,
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        include_events=None,
        batch_export_model=batch_export_model,
        use_json_type=True,
        min_ingested_timestamp=now,
        sort_key="event",
        expect_duplicates=True,
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

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=BATCH_EXPORTS_TASK_QUEUE,
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
                task_queue=BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(seconds=60),
            )

        runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
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

        await assert_clickhouse_records_in_bigquery(
            bigquery_client=bigquery_client,
            clickhouse_client=clickhouse_client,
            table_id=table_id,
            dataset_id=bigquery_batch_export.destination.config["dataset_id"],
            team_id=ateam.pk,
            date_ranges=[(data_interval_start, data_interval_end)],
            exclude_events=exclude_events,
            include_events=None,
            batch_export_model=model,
            use_json_type=use_json_type,
            min_ingested_timestamp=TEST_TIME,
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

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=BATCH_EXPORTS_TASK_QUEUE,
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
                task_queue=BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(seconds=10),
            )

        runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
        assert len(runs) == 1

        run = runs[0]
        assert run.status == "Completed"
        assert run.records_completed == 0


@pytest.mark.parametrize(
    "data_interval_start",
    # This is set to 24 hours before the `data_interval_end` to ensure that the data created is outside the batch
    # interval.
    [TEST_TIME - dt.timedelta(hours=24)],
    indirect=True,
)
@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("use_json_type", [True], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="persons", schema=None)])
async def test_bigquery_export_workflow_backfill_earliest_persons(
    ateam,
    bigquery_client,
    bigquery_batch_export,
    clickhouse_client,
    data_interval_start,
    data_interval_end,
    generate_test_data,
    interval,
    model,
    table_id,
    use_json_type,
):
    """Test a `BigQueryBatchExportWorkflow` backfilling the persons model.

    We expect persons outside the batch interval to also be backfilled (i.e. persons that were updated
    more than an hour ago) when setting `is_earliest_backfill=True`.
    """
    workflow_id = str(uuid.uuid4())
    inputs = BigQueryBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(bigquery_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_model=model,
        backfill_details=BackfillDetails(
            backfill_id=None,
            start_at=None,
            end_at=data_interval_end.isoformat(),
            is_earliest_backfill=True,
        ),
        **bigquery_batch_export.destination.config,
    )
    _, persons = generate_test_data

    # Ensure some data outside batch interval has been created
    assert any(
        data_interval_end - person["_timestamp"].replace(tzinfo=dt.UTC) > dt.timedelta(hours=12) for person in persons
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=BATCH_EXPORTS_TASK_QUEUE,
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
                task_queue=BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(minutes=10),
            )

    runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"
    assert run.data_interval_start is None

    await assert_clickhouse_records_in_bigquery(
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        table_id=table_id,
        dataset_id=bigquery_batch_export.destination.config["dataset_id"],
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=model,
        use_json_type=use_json_type,
        sort_key="person_id",
    )


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
            task_queue=BATCH_EXPORTS_TASK_QUEUE,
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
                    task_queue=BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=20),
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
            task_queue=BATCH_EXPORTS_TASK_QUEUE,
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
                    task_queue=BATCH_EXPORTS_TASK_QUEUE,
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
            task_queue=BATCH_EXPORTS_TASK_QUEUE,
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
                task_queue=BATCH_EXPORTS_TASK_QUEUE,
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

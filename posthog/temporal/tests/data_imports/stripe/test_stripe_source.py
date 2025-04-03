import functools
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import mock
from urllib.parse import parse_qs, urlparse

import aioboto3
import pytest
import pytest_asyncio
from asgiref.sync import sync_to_async
from django.conf import settings
from django.test import override_settings
from dlt.common.configuration.specs.aws_credentials import AwsCredentials
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.constants import DATA_WAREHOUSE_TASK_QUEUE
from posthog.hogql.query import execute_hogql_query
from posthog.temporal.data_imports.external_data_job import ExternalDataJobWorkflow
from posthog.temporal.data_imports.pipelines.pipeline.pipeline import PipelineNonDLT
from posthog.temporal.data_imports.settings import ACTIVITIES
from posthog.temporal.utils import ExternalDataWorkflowInputs
from posthog.warehouse.models import (
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
)
from posthog.warehouse.models.external_data_job import get_latest_run_if_exists
from posthog.warehouse.models.external_table_definitions import external_tables

from .data import BALANCE_TRANSACTIONS

BUCKET_NAME = "test-pipeline"
SESSION = aioboto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


@pytest_asyncio.fixture(autouse=True)
async def minio_client():
    """Manage an S3 client to interact with a MinIO bucket.

    Yields the client after creating a bucket. Upon resuming, we delete
    the contents and the bucket itself.
    """
    async with create_test_client(
        "s3",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    ) as minio_client:
        try:
            await minio_client.head_bucket(Bucket=BUCKET_NAME)
        except:
            await minio_client.create_bucket(Bucket=BUCKET_NAME)

        yield minio_client


def _mock_to_session_credentials(class_self):
    return {
        "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
        "aws_session_token": None,
        "AWS_ALLOW_HTTP": "true",
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
    }


def _mock_to_object_store_rs_credentials(class_self):
    return {
        "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
        "region": "us-east-1",
        "AWS_ALLOW_HTTP": "true",
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
    }


@pytest.fixture
def external_data_source(team):
    source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )
    return source


@pytest.fixture
def external_data_schema_full_refresh(external_data_source, team):
    schema = ExternalDataSchema.objects.create(
        name="BalanceTransaction",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="full_refresh",
        sync_type_config={},
    )
    return schema


@pytest.fixture
def external_data_schema_incremental(external_data_source, team):
    schema = ExternalDataSchema.objects.create(
        name="BalanceTransaction",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="incremental",
        sync_type_config={"incremental_field": "created", "incremental_field_type": "integer"},
    )
    return schema


async def _run_test(
    team,
    external_data_source,
    external_data_schema,
    mock_stripe_api,
    table_name,
    expected_rows_synced,
    expected_total_rows,
):
    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=external_data_source.pk,
        external_data_schema_id=external_data_schema.id,
        billable=False,
    )

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        mock.patch(
            "posthog.temporal.data_imports.pipelines.pipeline.pipeline.trigger_compaction_job"
        ) as mock_trigger_compaction_job,
        mock.patch(
            "posthog.temporal.data_imports.external_data_job.get_data_import_finished_metric"
        ) as mock_get_data_import_finished_metric,
        # mock the chunk size to 1 so we can test how iterating over chunks of data works, particularly with updating
        # the incremental field last value
        mock.patch.object(PipelineNonDLT, "_chunk_size", 1),
        mock.patch.object(AwsCredentials, "to_session_credentials", _mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", _mock_to_object_store_rs_credentials),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[ExternalDataJobWorkflow],
                activities=ACTIVITIES,  # type: ignore
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                await activity_environment.client.execute_workflow(
                    ExternalDataJobWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    # if not ignore_assertions:
    run: ExternalDataJob = await get_latest_run_if_exists(team_id=team.pk, pipeline_id=external_data_source.pk)

    assert run is not None
    assert run.status == ExternalDataJob.Status.COMPLETED
    assert run.rows_synced == expected_rows_synced

    mock_trigger_compaction_job.assert_called()
    mock_get_data_import_finished_metric.assert_called_with(
        source_type=external_data_source.source_type, status=ExternalDataJob.Status.COMPLETED.lower()
    )

    await external_data_schema.arefresh_from_db()

    assert external_data_schema.last_synced_at == run.created_at

    res = await sync_to_async(execute_hogql_query)(f"SELECT * FROM {table_name}", team)
    assert len(res.results) == expected_total_rows

    for name, field in external_tables.get(table_name, {}).items():
        if field.hidden:
            continue
        assert name in (res.columns or [])

    await external_data_schema.arefresh_from_db()
    assert external_data_schema.sync_type_config.get("reset_pipeline", None) is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_source_full_refresh(
    team, mock_stripe_api, external_data_source, external_data_schema_full_refresh
):
    """Test that a full refresh sync works as expected.

    We expect a single API call to be made to our mock Stripe API, which returns all the balance transactions.
    """
    table_name = "stripe_balancetransaction"
    expected_num_rows = len(BALANCE_TRANSACTIONS)

    await _run_test(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_full_refresh,
        mock_stripe_api=mock_stripe_api,
        table_name=table_name,
        expected_rows_synced=expected_num_rows,
        expected_total_rows=expected_num_rows,
    )

    # Check that the API was called as expected
    api_calls_made = mock_stripe_api.get_all_api_calls()
    assert len(api_calls_made) == 1
    assert api_calls_made[0].url == "https://api.stripe.com/v1/balance_transactions?limit=100"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_source_incremental(team, mock_stripe_api, external_data_source, external_data_schema_incremental):
    """Test that an incremental sync works as expected.

    We set the 'max_created' value to the created timestamp of the third item in the BALANCE_TRANSACTIONS list. This
    means on the first sync it will return all the data, except for the most recent 2 balance transactions.

    Then, after resetting the 'max_created' value, we expect the incremental sync to return the most recent 2 balance
    transactions when it is called again.
    """
    table_name = "stripe_balancetransaction"

    # mock the API so it doesn't return all data on initial sync
    third_item_created = BALANCE_TRANSACTIONS[2]["created"]
    mock_stripe_api.set_max_created(third_item_created)
    expected_rows_synced = 3
    expected_total_rows = 3

    await _run_test(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_incremental,
        mock_stripe_api=mock_stripe_api,
        table_name=table_name,
        expected_rows_synced=expected_rows_synced,
        expected_total_rows=expected_total_rows,
    )

    # Check that the API was called as expected
    api_calls_made = mock_stripe_api.get_all_api_calls()
    assert len(api_calls_made) == 1
    assert parse_qs(urlparse(api_calls_made[0].url).query) == {
        "created[gt]": ["0"],
        "limit": ["100"],
    }

    mock_stripe_api.reset_max_created()
    # run the incremental sync
    # we expect this to bring in 2 more rows
    expected_rows_synced = 2
    expected_total_rows = len(BALANCE_TRANSACTIONS)

    await _run_test(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_incremental,
        mock_stripe_api=mock_stripe_api,
        table_name=table_name,
        expected_rows_synced=expected_rows_synced,
        expected_total_rows=expected_total_rows,
    )

    api_calls_made = mock_stripe_api.get_all_api_calls()
    # Check that the API was called once more
    assert len(api_calls_made) == 2
    assert parse_qs(urlparse(api_calls_made[1].url).query) == {
        "created[gt]": [f"{third_item_created}"],
        "limit": ["100"],
    }

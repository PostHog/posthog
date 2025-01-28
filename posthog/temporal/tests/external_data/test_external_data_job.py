from concurrent.futures import ThreadPoolExecutor
import os
import uuid
from unittest import mock
from typing import Any, Optional
import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings

from posthog.temporal.data_imports import import_data_activity_sync
from posthog.temporal.data_imports.external_data_job import (
    UpdateExternalDataJobStatusInputs,
    create_source_templates,
    update_external_data_job_model,
)
from posthog.temporal.data_imports.external_data_job import (
    ExternalDataJobWorkflow,
    ExternalDataWorkflowInputs,
    Any_Source_Errors,
)
from posthog.temporal.data_imports.pipelines.pipeline.pipeline import PipelineNonDLT
from posthog.temporal.data_imports.workflow_activities.check_billing_limits import check_billing_limits_activity
from posthog.temporal.data_imports.workflow_activities.create_job_model import (
    CreateExternalDataJobModelActivityInputs,
    create_external_data_job_model_activity,
)
from posthog.temporal.data_imports.workflow_activities.import_data_sync import ImportDataActivityInputs
from posthog.temporal.data_imports.workflow_activities.sync_new_schemas import (
    SyncNewSchemasActivityInputs,
    sync_new_schemas_activity,
)
from posthog.warehouse.models import (
    get_latest_run_if_exists,
    ExternalDataJob,
    ExternalDataSource,
    ExternalDataSchema,
)

from posthog.temporal.data_imports.pipelines.schemas import (
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)
from posthog.models import Team
from temporalio.testing import WorkflowEnvironment
from temporalio.common import RetryPolicy
from temporalio.worker import UnsandboxedWorkflowRunner, Worker
from posthog.constants import DATA_WAREHOUSE_TASK_QUEUE
import pytest_asyncio
import boto3
import functools
from django.conf import settings
from dlt.sources.helpers.rest_client.client import RESTClient
from dlt.common.configuration.specs.aws_credentials import AwsCredentials
import psycopg

from posthog.warehouse.models.external_data_schema import get_all_schemas_for_source_id

BUCKET_NAME = "test-pipeline"
SESSION = boto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


def delete_all_from_s3(minio_client, bucket_name: str, key_prefix: str):
    """Delete all objects in bucket_name under key_prefix."""
    response = minio_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)

    if "Contents" in response:
        for obj in response["Contents"]:
            if "Key" in obj:
                minio_client.delete_object(Bucket=bucket_name, Key=obj["Key"])


@pytest.fixture
def bucket_name(request) -> str:
    """Name for a test S3 bucket."""
    return BUCKET_NAME


@pytest.fixture
def minio_client(bucket_name):
    """Manage an S3 client to interact with a MinIO bucket.

    Yields the client after creating a bucket. Upon resuming, we delete
    the contents and the bucket itself.
    """
    minio_client = create_test_client(
        "s3",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    )

    try:
        minio_client.head_bucket(Bucket=bucket_name)
    except:
        minio_client.create_bucket(Bucket=bucket_name)

    yield minio_client

    delete_all_from_s3(minio_client, bucket_name, key_prefix="/")

    minio_client.delete_bucket(Bucket=bucket_name)


@pytest.fixture
def postgres_config():
    return {
        "user": settings.PG_USER,
        "password": settings.PG_PASSWORD,
        "database": "external_data_database",
        "schema": "external_data_schema",
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


def _create_schema(schema_name: str, source: ExternalDataSource, team: Team, table_id: Optional[str] = None):
    return ExternalDataSchema.objects.create(
        name=schema_name,
        team_id=team.pk,
        source_id=source.pk,
        table_id=table_id,
    )


def _create_external_data_job(
    external_data_source_id: uuid.UUID,
    external_data_schema_id: uuid.UUID,
    workflow_id: str,
    workflow_run_id: str,
    team_id: int,
) -> ExternalDataJob:
    job = ExternalDataJob.objects.create(
        team_id=team_id,
        pipeline_id=external_data_source_id,
        schema_id=external_data_schema_id,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        pipeline_version=ExternalDataJob.PipelineVersion.V1,
    )

    return job


@pytest.mark.django_db(transaction=True)
def test_create_external_job_activity(activity_environment, team, **kwargs):
    """
    Test that the create external job activity creates a new job
    """
    new_source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Stripe",
    )

    test_1_schema = _create_schema("test-1", new_source, team)

    inputs = CreateExternalDataJobModelActivityInputs(
        team_id=team.id, source_id=new_source.pk, schema_id=test_1_schema.id, billable=True
    )

    run_id, _, __ = activity_environment.run(create_external_data_job_model_activity, inputs)

    runs = ExternalDataJob.objects.filter(id=run_id)
    assert runs.exists()


@pytest.mark.django_db(transaction=True)
def test_create_external_job_activity_schemas_exist(activity_environment, team, **kwargs):
    new_source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Stripe",
    )

    schema = ExternalDataSchema.objects.create(
        name=PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[new_source.source_type][0],
        team_id=team.id,
        source_id=new_source.pk,
    )

    inputs = CreateExternalDataJobModelActivityInputs(
        team_id=team.id, source_id=new_source.pk, schema_id=schema.id, billable=True
    )

    run_id, _, __ = activity_environment.run(create_external_data_job_model_activity, inputs)

    runs = ExternalDataJob.objects.filter(id=run_id)
    assert runs.exists()


@pytest.mark.django_db(transaction=True)
def test_create_external_job_activity_update_schemas(activity_environment, team, **kwargs):
    new_source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Stripe",
    )

    ExternalDataSchema.objects.create(
        name=PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[new_source.source_type][0],
        team_id=team.id,
        source_id=new_source.pk,
        should_sync=True,
    )

    inputs = SyncNewSchemasActivityInputs(source_id=str(new_source.pk), team_id=team.id)

    activity_environment.run(sync_new_schemas_activity, inputs)

    all_schemas = get_all_schemas_for_source_id(new_source.pk, team.id)

    assert len(all_schemas) == len(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[ExternalDataSource.Type.STRIPE])


@pytest.mark.django_db(transaction=True)
def test_update_external_job_activity(activity_environment, team, **kwargs):
    """
    Test that the update external job activity updates the job status
    """
    new_source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Stripe",
    )

    schema = ExternalDataSchema.objects.create(
        name=PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[new_source.source_type][0],
        team_id=team.id,
        source_id=new_source.pk,
        should_sync=True,
    )

    new_job = _create_external_data_job(
        team_id=team.id,
        external_data_source_id=new_source.pk,
        workflow_id=activity_environment.info.workflow_id,
        workflow_run_id=activity_environment.info.workflow_run_id,
        external_data_schema_id=schema.id,
    )

    inputs = UpdateExternalDataJobStatusInputs(
        job_id=str(new_job.id),
        status=ExternalDataJob.Status.COMPLETED,
        latest_error=None,
        internal_error=None,
        schema_id=str(schema.pk),
        source_id=str(new_source.pk),
        team_id=team.id,
    )

    activity_environment.run(update_external_data_job_model, inputs)
    new_job.refresh_from_db()
    schema.refresh_from_db()

    assert new_job.status == ExternalDataJob.Status.COMPLETED
    assert schema.status == ExternalDataJob.Status.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_update_external_job_activity_with_retryable_error(activity_environment, team, **kwargs):
    new_source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Stripe",
    )

    schema = ExternalDataSchema.objects.create(
        name=PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[new_source.source_type][0],
        team_id=team.id,
        source_id=new_source.pk,
        should_sync=True,
    )

    new_job = _create_external_data_job(
        team_id=team.id,
        external_data_source_id=new_source.pk,
        workflow_id=activity_environment.info.workflow_id,
        workflow_run_id=activity_environment.info.workflow_run_id,
        external_data_schema_id=schema.id,
    )

    inputs = UpdateExternalDataJobStatusInputs(
        job_id=str(new_job.id),
        status=ExternalDataJob.Status.COMPLETED,
        latest_error=None,
        internal_error="Some other retryable error",
        schema_id=str(schema.pk),
        source_id=str(new_source.pk),
        team_id=team.id,
    )

    activity_environment.run(update_external_data_job_model, inputs)
    new_job.refresh_from_db()
    schema.refresh_from_db()

    assert new_job.status == ExternalDataJob.Status.COMPLETED
    assert schema.status == ExternalDataJob.Status.COMPLETED
    assert schema.should_sync is True


@pytest.mark.django_db(transaction=True)
def test_update_external_job_activity_with_non_retryable_error(activity_environment, team, **kwargs):
    new_source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Postgres",
    )

    schema = ExternalDataSchema.objects.create(
        name="test_123",
        team_id=team.id,
        source_id=new_source.pk,
        should_sync=True,
    )

    new_job = _create_external_data_job(
        team_id=team.id,
        external_data_source_id=new_source.pk,
        workflow_id=activity_environment.info.workflow_id,
        workflow_run_id=activity_environment.info.workflow_run_id,
        external_data_schema_id=schema.id,
    )

    inputs = UpdateExternalDataJobStatusInputs(
        job_id=str(new_job.id),
        status=ExternalDataJob.Status.COMPLETED,
        latest_error=None,
        internal_error="NoSuchTableError: TableA",
        schema_id=str(schema.pk),
        source_id=str(new_source.pk),
        team_id=team.id,
    )
    with mock.patch("posthog.warehouse.models.external_data_schema.external_data_workflow_exists", return_value=False):
        activity_environment.run(update_external_data_job_model, inputs)

    new_job.refresh_from_db()
    schema.refresh_from_db()

    assert new_job.status == ExternalDataJob.Status.COMPLETED
    assert schema.status == ExternalDataJob.Status.COMPLETED
    assert schema.should_sync is False


@pytest.mark.django_db(transaction=True)
def test_update_external_job_activity_with_not_source_sepecific_non_retryable_error(
    activity_environment, team, **kwargs
):
    new_source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Postgres",
    )

    schema = ExternalDataSchema.objects.create(
        name="test_123",
        team_id=team.id,
        source_id=new_source.pk,
        should_sync=True,
    )

    new_job = _create_external_data_job(
        team_id=team.id,
        external_data_source_id=new_source.pk,
        workflow_id=activity_environment.info.workflow_id,
        workflow_run_id=activity_environment.info.workflow_run_id,
        external_data_schema_id=schema.id,
    )

    inputs = UpdateExternalDataJobStatusInputs(
        job_id=str(new_job.id),
        status=ExternalDataJob.Status.COMPLETED,
        latest_error=None,
        internal_error=Any_Source_Errors[0],
        schema_id=str(schema.pk),
        source_id=str(new_source.pk),
        team_id=team.id,
    )
    with mock.patch("posthog.warehouse.models.external_data_schema.external_data_workflow_exists", return_value=False):
        activity_environment.run(update_external_data_job_model, inputs)

    new_job.refresh_from_db()
    schema.refresh_from_db()

    assert new_job.status == ExternalDataJob.Status.COMPLETED
    assert schema.status == ExternalDataJob.Status.COMPLETED
    assert schema.should_sync is False


@pytest.mark.django_db(transaction=True)
def test_run_stripe_job(activity_environment, team, minio_client, **kwargs):
    def setup_job_1():
        new_source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=team,
            status="running",
            source_type="Stripe",
            job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        )

        customer_schema = _create_schema("Customer", new_source, team)

        new_job: ExternalDataJob = ExternalDataJob.objects.create(
            team_id=team.id,
            pipeline_id=new_source.pk,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
            schema=customer_schema,
            pipeline_version=ExternalDataJob.PipelineVersion.V1,
        )

        new_job = ExternalDataJob.objects.get(id=new_job.id)

        inputs = ImportDataActivityInputs(
            team_id=team.id,
            run_id=str(new_job.pk),
            source_id=new_source.pk,
            schema_id=customer_schema.id,
        )

        return new_job, inputs

    def setup_job_2():
        new_source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=team,
            status="running",
            source_type="Stripe",
            job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        )

        charge_schema = _create_schema("Charge", new_source, team)

        new_job: ExternalDataJob = ExternalDataJob.objects.create(
            team_id=team.id,
            pipeline_id=new_source.pk,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
            schema=charge_schema,
            pipeline_version=ExternalDataJob.PipelineVersion.V1,
        )

        new_job = ExternalDataJob.objects.get(id=new_job.id)

        inputs = ImportDataActivityInputs(
            team_id=team.id,
            run_id=str(new_job.pk),
            source_id=new_source.pk,
            schema_id=charge_schema.id,
        )

        return new_job, inputs

    job_1, job_1_inputs = setup_job_1()
    job_2, job_2_inputs = setup_job_2()

    def mock_customers_paginate(
        class_self,
        path: str = "",
        method: Any = "GET",
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        auth: Optional[Any] = None,
        paginator: Optional[Any] = None,
        data_selector: Optional[Any] = None,
        hooks: Optional[Any] = None,
    ):
        return iter(
            [
                {
                    "id": "cus_123",
                    "name": "John Doe",
                }
            ]
        )

    def mock_charges_paginate(
        class_self,
        path: str = "",
        method: Any = "GET",
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        auth: Optional[Any] = None,
        paginator: Optional[Any] = None,
        data_selector: Optional[Any] = None,
        hooks: Optional[Any] = None,
    ):
        return iter(
            [
                {
                    "id": "chg_123",
                    "customer": "cus_1",
                }
            ]
        )

    def mock_to_session_credentials(class_self):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(class_self):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    with (
        mock.patch.object(RESTClient, "paginate", mock_customers_paginate),
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            BUCKET_NAME=BUCKET_NAME,
        ),
        # Mock os.environ for the deltalake subprocess
        mock.patch.dict(
            os.environ,
            {
                "BUCKET_URL": f"s3://{BUCKET_NAME}",
                "AIRBYTE_BUCKET_KEY": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                "AIRBYTE_BUCKET_SECRET": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                "AIRBYTE_BUCKET_REGION": "us-east-1",
                "BUCKET_NAME": BUCKET_NAME,
                "AIRBYTE_BUCKET_DOMAIN": "objectstorage:19000",
            },
        ),
        mock.patch(
            "posthog.warehouse.models.table.DataWarehouseTable.get_columns",
            return_value={
                "id": {"clickhouse": "string", "hogql": "StringDatabaseField"},
                "name": {"clickhouse": "string", "hogql": "StringDatabaseField"},
            },
        ),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
    ):
        activity_environment.run(import_data_activity_sync, job_1_inputs)

        folder_path = job_1.folder_path()
        job_1_customer_objects = minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"{folder_path}/customer/")

        assert len(job_1_customer_objects["Contents"]) == 3

    with (
        mock.patch.object(RESTClient, "paginate", mock_charges_paginate),
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            BUCKET_NAME=BUCKET_NAME,
        ),
        # Mock os.environ for the deltalake subprocess
        mock.patch.dict(
            os.environ,
            {
                "BUCKET_URL": f"s3://{BUCKET_NAME}",
                "AIRBYTE_BUCKET_KEY": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                "AIRBYTE_BUCKET_SECRET": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                "AIRBYTE_BUCKET_REGION": "us-east-1",
                "BUCKET_NAME": BUCKET_NAME,
                "AIRBYTE_BUCKET_DOMAIN": "objectstorage:19000",
            },
        ),
        mock.patch(
            "posthog.warehouse.models.table.DataWarehouseTable.get_columns",
            return_value={
                "id": {"clickhouse": "string", "hogql": "StringDatabaseField"},
                "customer": {"clickhouse": "string", "hogql": "StringDatabaseField"},
            },
        ),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
    ):
        activity_environment.run(import_data_activity_sync, job_2_inputs)

        job_2_charge_objects = minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"{job_2.folder_path()}/charge/")
        assert len(job_2_charge_objects["Contents"]) == 3


@pytest.mark.django_db(transaction=True)
def test_run_stripe_job_row_count_update(activity_environment, team, minio_client, **kwargs):
    def setup_job_1():
        new_source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=team,
            status="running",
            source_type="Stripe",
            job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        )

        customer_schema = _create_schema("Customer", new_source, team)

        new_job: ExternalDataJob = ExternalDataJob.objects.create(
            team_id=team.id,
            pipeline_id=new_source.pk,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
            schema=customer_schema,
            pipeline_version=ExternalDataJob.PipelineVersion.V1,
        )

        new_job = (
            ExternalDataJob.objects.filter(id=new_job.id).prefetch_related("pipeline").prefetch_related("schema").get()
        )

        inputs = ImportDataActivityInputs(
            team_id=team.id,
            run_id=str(new_job.pk),
            source_id=new_source.pk,
            schema_id=customer_schema.id,
        )

        return new_job, inputs

    job_1, job_1_inputs = setup_job_1()

    def mock_customers_paginate(
        class_self,
        path: str = "",
        method: Any = "GET",
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        auth: Optional[Any] = None,
        paginator: Optional[Any] = None,
        data_selector: Optional[Any] = None,
        hooks: Optional[Any] = None,
    ):
        return iter(
            [
                {
                    "id": "cus_123",
                    "name": "John Doe",
                }
            ]
        )

    def mock_to_session_credentials(class_self):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(class_self):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    with (
        mock.patch.object(RESTClient, "paginate", mock_customers_paginate),
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            BUCKET_NAME=BUCKET_NAME,
        ),
        # Mock os.environ for the deltalake subprocess
        mock.patch.dict(
            os.environ,
            {
                "BUCKET_URL": f"s3://{BUCKET_NAME}",
                "AIRBYTE_BUCKET_KEY": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                "AIRBYTE_BUCKET_SECRET": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                "AIRBYTE_BUCKET_REGION": "us-east-1",
                "BUCKET_NAME": BUCKET_NAME,
                "AIRBYTE_BUCKET_DOMAIN": "objectstorage:19000",
            },
        ),
        mock.patch(
            "posthog.warehouse.models.table.DataWarehouseTable.get_columns",
            return_value={
                "id": {"clickhouse": "string", "hogql": "StringDatabaseField"},
                "name": {"clickhouse": "string", "hogql": "StringDatabaseField"},
            },
        ),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
    ):
        activity_environment.run(import_data_activity_sync, job_1_inputs)

        folder_path = job_1.folder_path()
        job_1_customer_objects = minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"{folder_path}/customer/")

        assert len(job_1_customer_objects["Contents"]) == 3

        job_1.refresh_from_db()
        assert job_1.rows_synced == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_external_data_job_workflow_with_schema(team, **kwargs):
    """
    Test workflow with schema.
    """
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name="Customer",
        team_id=team.id,
        source_id=new_source.pk,
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=new_source.pk,
        external_data_schema_id=schema.id,
    )

    def mock_func(inputs):
        return {}

    with (
        mock.patch("posthog.warehouse.models.table.DataWarehouseTable.get_columns", return_value={"id": "string"}),
        mock.patch.object(PipelineNonDLT, "run", mock_func),
    ):
        with (
            override_settings(
                BUCKET_URL=f"s3://{BUCKET_NAME}",
                AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                AIRBYTE_BUCKET_REGION="us-east-1",
                AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
                BUCKET_NAME=BUCKET_NAME,
            ),
            mock.patch.dict(  # Mock os.environ for the deltalake subprocess
                os.environ,
                {
                    "BUCKET_URL": f"s3://{BUCKET_NAME}",
                    "AIRBYTE_BUCKET_KEY": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                    "AIRBYTE_BUCKET_SECRET": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                    "AIRBYTE_BUCKET_REGION": "us-east-1",
                    "BUCKET_NAME": BUCKET_NAME,
                    "AIRBYTE_BUCKET_DOMAIN": "objectstorage:19000",
                },
            ),
        ):
            async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
                async with Worker(
                    activity_environment.client,
                    task_queue=DATA_WAREHOUSE_TASK_QUEUE,
                    workflows=[ExternalDataJobWorkflow],
                    activities=[
                        create_external_data_job_model_activity,
                        update_external_data_job_model,
                        import_data_activity_sync,
                        create_source_templates,
                        check_billing_limits_activity,
                        sync_new_schemas_activity,
                    ],
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

    run = await get_latest_run_if_exists(team_id=team.pk, pipeline_id=new_source.pk)

    assert run is not None
    assert run.status == ExternalDataJob.Status.COMPLETED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_run_postgres_job(
    activity_environment, team, minio_client, postgres_connection, postgres_config, **kwargs
):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.posthog_test (id integer)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.posthog_test (id) VALUES (1)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.commit()

    async def setup_job_1():
        new_source = await sync_to_async(ExternalDataSource.objects.create)(
            source_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            destination_id=uuid.uuid4(),
            team=team,
            status="running",
            source_type="Postgres",
            job_inputs={
                "host": postgres_config["host"],
                "port": postgres_config["port"],
                "database": postgres_config["database"],
                "user": postgres_config["user"],
                "password": postgres_config["password"],
                "schema": postgres_config["schema"],
                "ssh_tunnel_enabled": False,
            },
        )

        posthog_test_schema = await sync_to_async(_create_schema)("posthog_test", new_source, team)

        new_job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.create)(
            team_id=team.id,
            pipeline_id=new_source.pk,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
            schema=posthog_test_schema,
            pipeline_version=ExternalDataJob.PipelineVersion.V1,
        )

        new_job = await sync_to_async(
            ExternalDataJob.objects.filter(id=new_job.id).prefetch_related("pipeline").prefetch_related("schema").get
        )()

        inputs = ImportDataActivityInputs(
            team_id=team.id, run_id=str(new_job.pk), source_id=new_source.pk, schema_id=posthog_test_schema.id
        )

        return new_job, inputs

    job_1, job_1_inputs = await setup_job_1()

    def mock_to_session_credentials(class_self):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(class_self):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
            BUCKET_NAME=BUCKET_NAME,
        ),
        # Mock os.environ for the deltalake subprocess
        mock.patch.dict(
            os.environ,
            {
                "BUCKET_URL": f"s3://{BUCKET_NAME}",
                "AIRBYTE_BUCKET_KEY": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                "AIRBYTE_BUCKET_SECRET": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                "AIRBYTE_BUCKET_REGION": "us-east-1",
                "BUCKET_NAME": BUCKET_NAME,
                "AIRBYTE_BUCKET_DOMAIN": "objectstorage:19000",
            },
        ),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
    ):
        await sync_to_async(activity_environment.run)(import_data_activity_sync, job_1_inputs)

        folder_path = await sync_to_async(job_1.folder_path)()
        job_1_team_objects = minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"{folder_path}/posthog_test/")
        assert len(job_1_team_objects["Contents"]) == 3

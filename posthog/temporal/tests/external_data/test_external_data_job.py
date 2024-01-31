import uuid
from unittest import mock

import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings

from posthog.temporal.data_imports.external_data_job import (
    CreateExternalDataJobInputs,
    UpdateExternalDataJobStatusInputs,
    ValidateSchemaInputs,
    create_external_data_job,
    create_external_data_job_model,
    run_external_data_job,
    update_external_data_job_model,
    validate_schema_activity,
)
from posthog.temporal.data_imports.external_data_job import (
    ExternalDataJobWorkflow,
    ExternalDataJobInputs,
    ExternalDataWorkflowInputs,
)
from posthog.warehouse.models import (
    get_latest_run_if_exists,
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSource,
    ExternalDataSchema,
    DataWarehouseCredential,
)

from posthog.temporal.data_imports.pipelines.schemas import (
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)
from posthog.temporal.data_imports.pipelines.pipeline import DataImportPipeline
from temporalio.testing import WorkflowEnvironment
from temporalio.common import RetryPolicy
from temporalio.worker import UnsandboxedWorkflowRunner, Worker
from posthog.constants import DATA_WAREHOUSE_TASK_QUEUE
import pytest_asyncio
import aioboto3
import functools
from django.conf import settings
import asyncio
import psycopg

BUCKET_NAME = "test-external-data-jobs"
SESSION = aioboto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)

AWS_BUCKET_MOCK_SETTINGS = {
    "AIRBYTE_BUCKET_KEY": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
    "AIRBYTE_BUCKET_SECRET": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
}


async def delete_all_from_s3(minio_client, bucket_name: str, key_prefix: str):
    """Delete all objects in bucket_name under key_prefix."""
    response = await minio_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)

    if "Contents" in response:
        for obj in response["Contents"]:
            if "Key" in obj:
                await minio_client.delete_object(Bucket=bucket_name, Key=obj["Key"])


@pytest.fixture
def bucket_name(request) -> str:
    """Name for a test S3 bucket."""
    return BUCKET_NAME


@pytest_asyncio.fixture
async def minio_client(bucket_name):
    """Manage an S3 client to interact with a MinIO bucket.

    Yields the client after creating a bucket. Upon resuming, we delete
    the contents and the bucket itself.
    """
    async with create_test_client(
        "s3",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    ) as minio_client:
        await minio_client.create_bucket(Bucket=bucket_name)

        yield minio_client

        await delete_all_from_s3(minio_client, bucket_name, key_prefix="/")

        await minio_client.delete_bucket(Bucket=bucket_name)


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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_external_job_activity(activity_environment, team, **kwargs):
    """
    Test that the create external job activity creates a new job
    """
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
    )  # type: ignore

    inputs = CreateExternalDataJobInputs(team_id=team.id, external_data_source_id=new_source.pk)

    run_id, schemas = await activity_environment.run(create_external_data_job_model, inputs)

    runs = ExternalDataJob.objects.filter(id=run_id)
    assert await sync_to_async(runs.exists)()  # type:ignore
    assert len(schemas) == 0
    count = await sync_to_async(ExternalDataSchema.objects.filter(source_id=new_source.pk).count)()  # type:ignore
    assert count == len(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[new_source.source_type])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_external_job_activity_schemas_exist(activity_environment, team, **kwargs):
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
    )  # type: ignore

    await sync_to_async(ExternalDataSchema.objects.create)(  # type: ignore
        name=PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[new_source.source_type][0],
        team_id=team.id,
        source_id=new_source.pk,
    )

    await sync_to_async(ExternalDataSchema.objects.create)(  # type: ignore
        name=PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[new_source.source_type][1],
        team_id=team.id,
        source_id=new_source.pk,
        should_sync=False,
    )

    inputs = CreateExternalDataJobInputs(team_id=team.id, external_data_source_id=new_source.pk)

    run_id, schemas = await activity_environment.run(create_external_data_job_model, inputs)

    runs = ExternalDataJob.objects.filter(id=run_id)
    assert await sync_to_async(runs.exists)()  # type:ignore
    assert len(schemas) == 1
    # doesn't overlap
    count = await sync_to_async(ExternalDataSchema.objects.filter(source_id=new_source.pk).count)()  # type:ignore
    assert count == len(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[new_source.source_type])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_external_job_activity(activity_environment, team, **kwargs):
    """
    Test that the update external job activity updates the job status
    """
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
    )  # type: ignore

    new_job = await sync_to_async(create_external_data_job)(
        team_id=team.id, external_data_source_id=new_source.pk, workflow_id=activity_environment.info.workflow_id
    )  # type: ignore

    inputs = UpdateExternalDataJobStatusInputs(
        id=str(new_job.id),
        run_id=str(new_job.id),
        status=ExternalDataJob.Status.COMPLETED,
        latest_error=None,
        team_id=team.id,
    )

    await activity_environment.run(update_external_data_job_model, inputs)
    await sync_to_async(new_job.refresh_from_db)()  # type: ignore

    assert new_job.status == ExternalDataJob.Status.COMPLETED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_run_stripe_job(activity_environment, team, minio_client, **kwargs):
    async def setup_job_1():
        new_source = await sync_to_async(ExternalDataSource.objects.create)(
            source_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            destination_id=uuid.uuid4(),
            team=team,
            status="running",
            source_type="Stripe",
            job_inputs={"stripe_secret_key": "test-key"},
        )  # type: ignore

        new_job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.create)(  # type: ignore
            team_id=team.id,
            pipeline_id=new_source.pk,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
        )

        new_job = await sync_to_async(ExternalDataJob.objects.filter(id=new_job.id).prefetch_related("pipeline").get)()  # type: ignore

        schemas = ["Customer"]
        inputs = ExternalDataJobInputs(
            team_id=team.id,
            run_id=new_job.pk,
            source_id=new_source.pk,
            schemas=schemas,
        )

        return new_job, inputs

    async def setup_job_2():
        new_source = await sync_to_async(ExternalDataSource.objects.create)(
            source_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            destination_id=uuid.uuid4(),
            team=team,
            status="running",
            source_type="Stripe",
            job_inputs={"stripe_secret_key": "test-key"},
        )  # type: ignore

        new_job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.create)(  # type: ignore
            team_id=team.id,
            pipeline_id=new_source.pk,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
        )

        new_job = await sync_to_async(ExternalDataJob.objects.filter(id=new_job.id).prefetch_related("pipeline").get)()  # type: ignore

        schemas = ["Customer", "Invoice"]
        inputs = ExternalDataJobInputs(
            team_id=team.id,
            run_id=new_job.pk,
            source_id=new_source.pk,
            schemas=schemas,
        )

        return new_job, inputs

    job_1, job_1_inputs = await setup_job_1()
    job_2, job_2_inputs = await setup_job_2()

    with mock.patch("stripe.Customer.list") as mock_customer_list, mock.patch(
        "stripe.Invoice.list"
    ) as mock_invoice_list, override_settings(
        BUCKET_URL=f"s3://{BUCKET_NAME}",
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    ):
        mock_customer_list.return_value = {
            "data": [
                {
                    "id": "cus_123",
                    "name": "John Doe",
                }
            ],
            "has_more": False,
        }

        mock_invoice_list.return_value = {
            "data": [
                {
                    "id": "inv_123",
                    "customer": "cus_1",
                }
            ],
            "has_more": False,
        }
        await asyncio.gather(
            activity_environment.run(run_external_data_job, job_1_inputs),
            activity_environment.run(run_external_data_job, job_2_inputs),
        )

        job_1_customer_objects = await minio_client.list_objects_v2(
            Bucket=BUCKET_NAME, Prefix=f"{job_1.folder_path}/customer/"
        )
        job_1_invoice_objects = await minio_client.list_objects_v2(
            Bucket=BUCKET_NAME, Prefix=f"{job_1.folder_path}/invoice/"
        )
        assert len(job_1_customer_objects["Contents"]) == 1
        assert job_1_invoice_objects.get("Contents", None) is None

        job_2_customer_objects = await minio_client.list_objects_v2(
            Bucket=BUCKET_NAME, Prefix=f"{job_2.folder_path}/customer/"
        )
        job_2_invoice_objects = await minio_client.list_objects_v2(
            Bucket=BUCKET_NAME, Prefix=f"{job_2.folder_path}/invoice/"
        )
        assert len(job_2_customer_objects["Contents"]) == 1
        assert len(job_2_invoice_objects["Contents"]) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_validate_schema_and_update_table_activity(activity_environment, team, **kwargs):
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key"},
    )  # type: ignore

    new_job = await sync_to_async(ExternalDataJob.objects.create)(  # type: ignore
        team_id=team.id,
        pipeline_id=new_source.pk,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
    )

    with mock.patch(
        "posthog.warehouse.models.table.DataWarehouseTable.get_columns"
    ) as mock_get_columns, override_settings(**AWS_BUCKET_MOCK_SETTINGS):
        mock_get_columns.return_value = {"id": "string"}
        await activity_environment.run(
            validate_schema_activity,
            ValidateSchemaInputs(
                run_id=new_job.pk, team_id=team.id, schemas=["test-1", "test-2", "test-3", "test-4", "test-5"]
            ),
        )

        assert mock_get_columns.call_count == 10
        assert (
            await sync_to_async(DataWarehouseTable.objects.filter(external_data_source_id=new_source.pk).count)() == 5  # type: ignore
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_validate_schema_and_update_table_activity_with_existing(activity_environment, team, **kwargs):
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key"},
    )  # type: ignore

    old_job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.create)(  # type: ignore
        team_id=team.id,
        pipeline_id=new_source.pk,
        status=ExternalDataJob.Status.COMPLETED,
        rows_synced=0,
    )

    old_credential = await sync_to_async(DataWarehouseCredential.objects.create)(  # type: ignore
        team=team,
        access_key=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        access_secret=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    )

    url_pattern = await sync_to_async(old_job.url_pattern_by_schema)("test-1")

    await sync_to_async(DataWarehouseTable.objects.create)(  # type: ignore
        credential=old_credential,
        name="stripe_test-1",
        format="Parquet",
        url_pattern=url_pattern,
        team_id=team.pk,
        external_data_source_id=new_source.pk,
    )

    new_job = await sync_to_async(ExternalDataJob.objects.create)(  # type: ignore
        team_id=team.id,
        pipeline_id=new_source.pk,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
    )

    with mock.patch(
        "posthog.warehouse.models.table.DataWarehouseTable.get_columns"
    ) as mock_get_columns, override_settings(**AWS_BUCKET_MOCK_SETTINGS):
        mock_get_columns.return_value = {"id": "string"}
        await activity_environment.run(
            validate_schema_activity,
            ValidateSchemaInputs(
                run_id=new_job.pk, team_id=team.id, schemas=["test-1", "test-2", "test-3", "test-4", "test-5"]
            ),
        )

        assert mock_get_columns.call_count == 10
        assert (
            await sync_to_async(DataWarehouseTable.objects.filter(external_data_source_id=new_source.pk).count)() == 5  # type: ignore
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_validate_schema_and_update_table_activity_half_run(activity_environment, team, **kwargs):
    new_source = await sync_to_async(ExternalDataSource.objects.create)(  # type: ignore
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key"},
    )

    new_job = await sync_to_async(ExternalDataJob.objects.create)(  # type: ignore
        team_id=team.id,
        pipeline_id=new_source.pk,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
    )

    with mock.patch("posthog.warehouse.models.table.DataWarehouseTable.get_columns") as mock_get_columns, mock.patch(
        "posthog.warehouse.data_load.validate_schema.validate_schema",
    ) as mock_validate, override_settings(**AWS_BUCKET_MOCK_SETTINGS):
        mock_get_columns.return_value = {"id": "string"}
        credential = await sync_to_async(DataWarehouseCredential.objects.create)(  # type: ignore
            team=team,
            access_key=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            access_secret=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        )

        mock_validate.side_effect = [
            Exception,
            {
                "credential": credential,
                "format": "Parquet",
                "name": "test_schema",
                "url_pattern": "test_url_pattern",
                "team_id": team.pk,
            },
        ]

        await activity_environment.run(
            validate_schema_activity,
            ValidateSchemaInputs(run_id=new_job.pk, team_id=team.id, schemas=["broken_schema", "test_schema"]),
        )

        assert mock_get_columns.call_count == 1
        assert (
            await sync_to_async(DataWarehouseTable.objects.filter(external_data_source_id=new_source.pk).count)() == 1  # type: ignore
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_schema_activity(activity_environment, team, **kwargs):
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key"},
    )  # type: ignore

    new_job = await sync_to_async(ExternalDataJob.objects.create)(  # type: ignore
        team_id=team.id,
        pipeline_id=new_source.pk,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
    )

    with mock.patch(
        "posthog.warehouse.models.table.DataWarehouseTable.get_columns"
    ) as mock_get_columns, override_settings(**AWS_BUCKET_MOCK_SETTINGS):
        mock_get_columns.return_value = {"id": "string"}
        await activity_environment.run(
            validate_schema_activity,
            ValidateSchemaInputs(
                run_id=new_job.pk, team_id=team.id, schemas=["test-1", "test-2", "test-3", "test-4", "test-5"]
            ),
        )

        assert mock_get_columns.call_count == 10
        all_tables = DataWarehouseTable.objects.all()
        table_length = await sync_to_async(len)(all_tables)  # type: ignore
        assert table_length == 5


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_external_data_job_workflow_blank(team, **kwargs):
    """
    Test workflow with no schema.
    Smoke test for making sure all activities run.
    """
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key"},
    )  # type: ignore

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=new_source.pk,
    )

    with override_settings(AIRBYTE_BUCKET_KEY="test-key", AIRBYTE_BUCKET_SECRET="test-secret"):
        with mock.patch.dict(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING, {ExternalDataSource.Type.STRIPE: ()}):
            async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
                async with Worker(
                    activity_environment.client,
                    task_queue=DATA_WAREHOUSE_TASK_QUEUE,
                    workflows=[ExternalDataJobWorkflow],
                    activities=[
                        create_external_data_job_model,
                        update_external_data_job_model,
                        run_external_data_job,
                        validate_schema_activity,
                    ],
                    workflow_runner=UnsandboxedWorkflowRunner(),
                ):
                    await activity_environment.client.execute_workflow(
                        ExternalDataJobWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=DATA_WAREHOUSE_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

    run = await sync_to_async(get_latest_run_if_exists)(team_id=team.pk, pipeline_id=new_source.pk)  # type: ignore
    assert run is not None
    assert run.status == ExternalDataJob.Status.COMPLETED


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
        job_inputs={"stripe_secret_key": "test-key"},
    )  # type: ignore

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=new_source.pk,
    )

    schemas = PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[new_source.source_type]
    for schema in schemas:
        await sync_to_async(ExternalDataSchema.objects.create)(  # type: ignore
            name=schema,
            team_id=team.id,
            source_id=new_source.pk,
        )

    async def mock_async_func(inputs):
        pass

    with mock.patch(
        "posthog.warehouse.models.table.DataWarehouseTable.get_columns", return_value={"id": "string"}
    ), mock.patch.object(DataImportPipeline, "run", mock_async_func):
        with override_settings(AIRBYTE_BUCKET_KEY="test-key", AIRBYTE_BUCKET_SECRET="test-secret"):
            async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
                async with Worker(
                    activity_environment.client,
                    task_queue=DATA_WAREHOUSE_TASK_QUEUE,
                    workflows=[ExternalDataJobWorkflow],
                    activities=[
                        create_external_data_job_model,
                        update_external_data_job_model,
                        run_external_data_job,
                        validate_schema_activity,
                    ],
                    workflow_runner=UnsandboxedWorkflowRunner(),
                ):
                    await activity_environment.client.execute_workflow(
                        ExternalDataJobWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=DATA_WAREHOUSE_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

    run = await sync_to_async(get_latest_run_if_exists)(team_id=team.pk, pipeline_id=new_source.pk)  # type: ignore

    assert run is not None
    assert run.status == ExternalDataJob.Status.COMPLETED

    assert await sync_to_async(DataWarehouseTable.objects.filter(external_data_source_id=new_source.pk).count)() == len(  # type: ignore
        PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[new_source.source_type]
    )


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
            },
        )  # type: ignore

        new_job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.create)(  # type: ignore
            team_id=team.id,
            pipeline_id=new_source.pk,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
        )

        new_job = await sync_to_async(ExternalDataJob.objects.filter(id=new_job.id).prefetch_related("pipeline").get)()  # type: ignore

        schemas = ["posthog_test"]
        inputs = ExternalDataJobInputs(
            team_id=team.id,
            run_id=new_job.pk,
            source_id=new_source.pk,
            schemas=schemas,
        )

        return new_job, inputs

    job_1, job_1_inputs = await setup_job_1()

    with override_settings(
        BUCKET_URL=f"s3://{BUCKET_NAME}",
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    ):
        await asyncio.gather(
            activity_environment.run(run_external_data_job, job_1_inputs),
        )

        job_1_team_objects = await minio_client.list_objects_v2(
            Bucket=BUCKET_NAME, Prefix=f"{job_1.folder_path}/posthog_test/"
        )
        assert len(job_1_team_objects["Contents"]) == 1

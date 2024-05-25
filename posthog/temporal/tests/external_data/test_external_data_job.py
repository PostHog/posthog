import uuid
from unittest import mock
from typing import Optional
import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings

from posthog.temporal.data_imports.external_data_job import (
    UpdateExternalDataJobStatusInputs,
    check_schedule_activity,
    create_source_templates,
    update_external_data_job_model,
)
from posthog.temporal.data_imports.external_data_job import (
    ExternalDataJobWorkflow,
    ExternalDataWorkflowInputs,
)
from posthog.temporal.data_imports.workflow_activities.create_job_model import (
    CreateExternalDataJobModelActivityInputs,
    create_external_data_job_model_activity,
)
from posthog.temporal.data_imports.workflow_activities.import_data import ImportDataActivityInputs, import_data_activity
from posthog.warehouse.external_data_source.jobs import create_external_data_job
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
from posthog.temporal.tests.utils.s3 import read_parquet_from_s3

from posthog.warehouse.models.external_data_schema import get_all_schemas_for_source_id
from posthog.warehouse.models.external_table_definitions import get_imported_fields_for_table

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


async def _create_schema(schema_name: str, source: ExternalDataSource, team: Team, table_id: Optional[str] = None):
    return await sync_to_async(ExternalDataSchema.objects.create)(
        name=schema_name,
        team_id=team.id,
        source_id=source.pk,
        table_id=table_id,
    )


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
    )

    test_1_schema = await _create_schema("test-1", new_source, team)

    inputs = CreateExternalDataJobModelActivityInputs(
        team_id=team.id, source_id=new_source.pk, schema_id=test_1_schema.id
    )

    run_id, _ = await activity_environment.run(create_external_data_job_model_activity, inputs)

    runs = ExternalDataJob.objects.filter(id=run_id)
    assert await sync_to_async(runs.exists)()


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
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[new_source.source_type][0],
        team_id=team.id,
        source_id=new_source.pk,
    )

    inputs = CreateExternalDataJobModelActivityInputs(team_id=team.id, source_id=new_source.pk, schema_id=schema.id)

    run_id, _ = await activity_environment.run(create_external_data_job_model_activity, inputs)

    runs = ExternalDataJob.objects.filter(id=run_id)
    assert await sync_to_async(runs.exists)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_external_job_activity_update_schemas(activity_environment, team, **kwargs):
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[new_source.source_type][0],
        team_id=team.id,
        source_id=new_source.pk,
        should_sync=True,
    )

    inputs = CreateExternalDataJobModelActivityInputs(team_id=team.id, source_id=new_source.pk, schema_id=schema.id)

    run_id, _ = await activity_environment.run(create_external_data_job_model_activity, inputs)

    runs = ExternalDataJob.objects.filter(id=run_id)
    assert await sync_to_async(runs.exists)()

    all_schemas = await sync_to_async(get_all_schemas_for_source_id)(new_source.pk, team.id)

    assert len(all_schemas) == len(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[ExternalDataSource.Type.STRIPE])


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
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[new_source.source_type][0],
        team_id=team.id,
        source_id=new_source.pk,
        should_sync=True,
    )

    new_job = await sync_to_async(create_external_data_job)(
        team_id=team.id,
        external_data_source_id=new_source.pk,
        workflow_id=activity_environment.info.workflow_id,
        external_data_schema_id=schema.id,
    )

    inputs = UpdateExternalDataJobStatusInputs(
        id=str(new_job.id),
        run_id=str(new_job.id),
        status=ExternalDataJob.Status.COMPLETED,
        latest_error=None,
        team_id=team.id,
    )

    await activity_environment.run(update_external_data_job_model, inputs)
    await sync_to_async(new_job.refresh_from_db)()
    await sync_to_async(schema.refresh_from_db)()

    assert new_job.status == ExternalDataJob.Status.COMPLETED
    assert schema.status == ExternalDataJob.Status.COMPLETED


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
        )

        new_job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.create)(
            team_id=team.id,
            pipeline_id=new_source.pk,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
        )

        new_job = await sync_to_async(ExternalDataJob.objects.filter(id=new_job.id).prefetch_related("pipeline").get)()

        customer_schema = await _create_schema("Customer", new_source, team)

        inputs = ImportDataActivityInputs(
            team_id=team.id,
            run_id=new_job.pk,
            source_id=new_source.pk,
            schema_id=customer_schema.id,
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
        )

        new_job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.create)(
            team_id=team.id,
            pipeline_id=new_source.pk,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
        )

        new_job = await sync_to_async(ExternalDataJob.objects.filter(id=new_job.id).prefetch_related("pipeline").get)()

        charge_schema = await _create_schema("Charge", new_source, team)

        inputs = ImportDataActivityInputs(
            team_id=team.id,
            run_id=new_job.pk,
            source_id=new_source.pk,
            schema_id=charge_schema.id,
        )

        return new_job, inputs

    job_1, job_1_inputs = await setup_job_1()
    job_2, job_2_inputs = await setup_job_2()

    with (
        mock.patch("stripe.Customer.list") as mock_customer_list,
        mock.patch("stripe.Charge.list") as mock_charge_list,
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        ),
        mock.patch(
            "posthog.warehouse.models.table.DataWarehouseTable.get_columns",
            return_value={"clickhouse": {"id": "string", "name": "string"}},
        ),
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

        mock_charge_list.return_value = {
            "data": [
                {
                    "id": "chg_123",
                    "customer": "cus_1",
                }
            ],
            "has_more": False,
        }
        await asyncio.gather(
            activity_environment.run(import_data_activity, job_1_inputs),
            activity_environment.run(import_data_activity, job_2_inputs),
        )

        job_1_customer_objects = await minio_client.list_objects_v2(
            Bucket=BUCKET_NAME, Prefix=f"{job_1.folder_path}/customer/"
        )

        assert len(job_1_customer_objects["Contents"]) == 1
        s3_data = await read_parquet_from_s3(
            BUCKET_NAME,
            job_1_customer_objects["Contents"][0]["Key"],
            {},
            settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        )
        customer_fields = get_imported_fields_for_table("stripe_customer")
        all_keys = list(s3_data[0].keys())

        assert len(s3_data) == 1
        assert all(field in all_keys for field in customer_fields)

        job_2_charge_objects = await minio_client.list_objects_v2(
            Bucket=BUCKET_NAME, Prefix=f"{job_2.folder_path}/charge/"
        )
        assert len(job_2_charge_objects["Contents"]) == 1

        s3_data = await read_parquet_from_s3(
            BUCKET_NAME,
            job_2_charge_objects["Contents"][0]["Key"],
            {},
            settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        )
        customer_fields = get_imported_fields_for_table("stripe_charge")
        all_keys = list(s3_data[0].keys())

        assert len(s3_data) == 1
        assert all(field in all_keys for field in customer_fields)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_run_stripe_job_cancelled(activity_environment, team, minio_client, **kwargs):
    async def setup_job_1():
        new_source = await sync_to_async(ExternalDataSource.objects.create)(
            source_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            destination_id=uuid.uuid4(),
            team=team,
            status="running",
            source_type="Stripe",
            job_inputs={"stripe_secret_key": "test-key"},
        )

        # Already canceled so it should only run once
        # This imitates if the job was canceled mid run
        new_job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.create)(
            team_id=team.id,
            pipeline_id=new_source.pk,
            status=ExternalDataJob.Status.CANCELLED,
            rows_synced=0,
        )

        new_job = await sync_to_async(ExternalDataJob.objects.filter(id=new_job.id).prefetch_related("pipeline").get)()

        customer_schema = await _create_schema("Customer", new_source, team)

        inputs = ImportDataActivityInputs(
            team_id=team.id,
            run_id=new_job.pk,
            source_id=new_source.pk,
            schema_id=customer_schema.id,
        )

        return new_job, inputs

    job_1, job_1_inputs = await setup_job_1()

    with (
        mock.patch("stripe.Customer.list") as mock_customer_list,
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        ),
    ):
        mock_customer_list.return_value = {
            "data": [
                {
                    "id": "cus_123",
                    "name": "John Doe",
                }
            ],
            "has_more": True,
        }
        await asyncio.gather(
            activity_environment.run(import_data_activity, job_1_inputs),
        )

        job_1_customer_objects = await minio_client.list_objects_v2(
            Bucket=BUCKET_NAME, Prefix=f"{job_1.folder_path}/customer/"
        )

        # if job was not canceled, this job would run indefinitely
        assert len(job_1_customer_objects["Contents"]) == 1

        await sync_to_async(job_1.refresh_from_db)()
        assert job_1.rows_synced == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_run_stripe_job_row_count_update(activity_environment, team, minio_client, **kwargs):
    async def setup_job_1():
        new_source = await sync_to_async(ExternalDataSource.objects.create)(
            source_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            destination_id=uuid.uuid4(),
            team=team,
            status="running",
            source_type="Stripe",
            job_inputs={"stripe_secret_key": "test-key"},
        )

        new_job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.create)(
            team_id=team.id,
            pipeline_id=new_source.pk,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
        )

        new_job = await sync_to_async(ExternalDataJob.objects.filter(id=new_job.id).prefetch_related("pipeline").get)()

        customer_schema = await _create_schema("Customer", new_source, team)

        inputs = ImportDataActivityInputs(
            team_id=team.id,
            run_id=new_job.pk,
            source_id=new_source.pk,
            schema_id=customer_schema.id,
        )

        return new_job, inputs

    job_1, job_1_inputs = await setup_job_1()

    with (
        mock.patch("stripe.Customer.list") as mock_customer_list,
        mock.patch("posthog.temporal.data_imports.pipelines.helpers.CHUNK_SIZE", 0),
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        ),
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
        await asyncio.gather(
            activity_environment.run(import_data_activity, job_1_inputs),
        )

        job_1_customer_objects = await minio_client.list_objects_v2(
            Bucket=BUCKET_NAME, Prefix=f"{job_1.folder_path}/customer/"
        )

        assert len(job_1_customer_objects["Contents"]) == 1

        await sync_to_async(job_1.refresh_from_db)()
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
        job_inputs={"stripe_secret_key": "test-key"},
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

    async def mock_async_func(inputs):
        return {}

    with (
        mock.patch("posthog.warehouse.models.table.DataWarehouseTable.get_columns", return_value={"id": "string"}),
        mock.patch.object(DataImportPipeline, "run", mock_async_func),
    ):
        with override_settings(AIRBYTE_BUCKET_KEY="test-key", AIRBYTE_BUCKET_SECRET="test-secret"):
            async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
                async with Worker(
                    activity_environment.client,
                    task_queue=DATA_WAREHOUSE_TASK_QUEUE,
                    workflows=[ExternalDataJobWorkflow],
                    activities=[
                        check_schedule_activity,
                        create_external_data_job_model_activity,
                        update_external_data_job_model,
                        import_data_activity,
                        create_source_templates,
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
            },
        )

        new_job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.create)(
            team_id=team.id,
            pipeline_id=new_source.pk,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
        )

        new_job = await sync_to_async(ExternalDataJob.objects.filter(id=new_job.id).prefetch_related("pipeline").get)()

        posthog_test_schema = await _create_schema("posthog_test", new_source, team)

        inputs = ImportDataActivityInputs(
            team_id=team.id, run_id=new_job.pk, source_id=new_source.pk, schema_id=posthog_test_schema.id
        )

        return new_job, inputs

    job_1, job_1_inputs = await setup_job_1()

    with override_settings(
        BUCKET_URL=f"s3://{BUCKET_NAME}",
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    ):
        await asyncio.gather(
            activity_environment.run(import_data_activity, job_1_inputs),
        )

        job_1_team_objects = await minio_client.list_objects_v2(
            Bucket=BUCKET_NAME, Prefix=f"{job_1.folder_path}/posthog_test/"
        )
        assert len(job_1_team_objects["Contents"]) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_check_schedule_activity_with_schema_id(activity_environment, team, **kwargs):
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key"},
    )

    test_1_schema = await _create_schema("test-1", new_source, team)

    should_exit = await activity_environment.run(
        check_schedule_activity,
        ExternalDataWorkflowInputs(
            team_id=team.id,
            external_data_source_id=new_source.id,
            external_data_schema_id=test_1_schema.id,
        ),
    )

    assert should_exit is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_check_schedule_activity_with_missing_schema_id_but_with_schedule(activity_environment, team, **kwargs):
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key"},
    )

    await sync_to_async(ExternalDataSchema.objects.create)(
        name="test-1",
        team_id=team.id,
        source_id=new_source.pk,
        should_sync=True,
    )

    with (
        mock.patch(
            "posthog.temporal.data_imports.external_data_job.a_external_data_workflow_exists", return_value=True
        ),
        mock.patch(
            "posthog.temporal.data_imports.external_data_job.a_delete_external_data_schedule", return_value=True
        ),
        mock.patch(
            "posthog.temporal.data_imports.external_data_job.a_trigger_external_data_workflow"
        ) as mock_a_trigger_external_data_workflow,
    ):
        should_exit = await activity_environment.run(
            check_schedule_activity,
            ExternalDataWorkflowInputs(
                team_id=team.id,
                external_data_source_id=new_source.id,
                external_data_schema_id=None,
            ),
        )

    assert should_exit is True
    assert mock_a_trigger_external_data_workflow.call_count == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_check_schedule_activity_with_missing_schema_id_and_no_schedule(activity_environment, team, **kwargs):
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key"},
    )

    await sync_to_async(ExternalDataSchema.objects.create)(
        name="test-1",
        team_id=team.id,
        source_id=new_source.pk,
        should_sync=True,
    )

    with (
        mock.patch(
            "posthog.temporal.data_imports.external_data_job.a_external_data_workflow_exists", return_value=False
        ),
        mock.patch(
            "posthog.temporal.data_imports.external_data_job.a_delete_external_data_schedule", return_value=True
        ),
        mock.patch(
            "posthog.temporal.data_imports.external_data_job.a_sync_external_data_job_workflow"
        ) as mock_a_sync_external_data_job_workflow,
    ):
        should_exit = await activity_environment.run(
            check_schedule_activity,
            ExternalDataWorkflowInputs(
                team_id=team.id,
                external_data_source_id=new_source.id,
                external_data_schema_id=None,
            ),
        )

    assert should_exit is True
    assert mock_a_sync_external_data_job_workflow.call_count == 1

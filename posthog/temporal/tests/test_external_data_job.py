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
from posthog.temporal.data_imports.pipelines.stripe.stripe_pipeline import (
    StripeJobInputs,
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
)

from posthog.temporal.data_imports.pipelines.stripe.stripe_pipeline import (
    PIPELINE_TYPE_RUN_MAPPING,
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)
from temporalio.testing import WorkflowEnvironment
from temporalio.common import RetryPolicy
from temporalio.worker import UnsandboxedWorkflowRunner, Worker
from posthog.constants import DATA_WAREHOUSE_TASK_QUEUE

AWS_BUCKET_MOCK_SETTINGS = {
    "AIRBYTE_BUCKET_KEY": "test-key",
    "AIRBYTE_BUCKET_SECRET": "test-secret",
}


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
    assert len(schemas) == len(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[new_source.source_type])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_external_job_activity_schemas_exist(activity_environment, team, **kwargs):
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
    # one less schema because one of the schemas is turned off
    assert len(schemas) == len(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[new_source.source_type]) - 1


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
async def test_run_stripe_job(activity_environment, team, **kwargs):
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

    inputs = ExternalDataJobInputs(
        team_id=team.id,
        run_id=new_job.pk,
        source_id=new_source.pk,
        schemas=["test-1", "test-2", "test-3", "test-4", "test-5"],
    )

    with mock.patch(
        "posthog.temporal.data_imports.pipelines.stripe.stripe_pipeline.create_pipeline",
    ) as mock_create_pipeline, mock.patch(
        "posthog.temporal.data_imports.pipelines.stripe.helpers.stripe_get_data"
    ) as mock_stripe_get_data:  # noqa: B015
        mock_stripe_get_data.return_value = {
            "data": [{"id": "test-id", "object": "test-object"}],
            "has_more": False,
        }
        await activity_environment.run(run_external_data_job, inputs)

        assert mock_stripe_get_data.call_count == 5
        assert mock_create_pipeline.call_count == 5

        mock_create_pipeline.assert_called_with(
            StripeJobInputs(
                source_id=new_source.pk,
                run_id=new_job.pk,
                job_type="Stripe",
                team_id=team.id,
                stripe_secret_key="test-key",
                dataset_name=new_job.folder_path,
                schemas=["test-1", "test-2", "test-3", "test-4", "test-5"],
            )
        )


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

    async def mock_async_func(inputs):
        pass

    with mock.patch(
        "posthog.warehouse.models.table.DataWarehouseTable.get_columns", return_value={"id": "string"}
    ), mock.patch.dict(PIPELINE_TYPE_RUN_MAPPING, {ExternalDataSource.Type.STRIPE: mock_async_func}):
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

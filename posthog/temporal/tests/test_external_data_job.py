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
from posthog.temporal.data_imports.external_data_job import ExternalDataJobInputs
from posthog.warehouse.models import (
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSource,
)

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

    run_id = await activity_environment.run(create_external_data_job_model, inputs)

    runs = ExternalDataJob.objects.filter(id=run_id)
    assert await sync_to_async(runs.exists)()  # type:ignore


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

    inputs = ExternalDataJobInputs(team_id=team.id, run_id=new_job.pk)

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
                run_id=new_job.pk,
                job_type="Stripe",
                team_id=team.id,
                stripe_secret_key="test-key",
                dataset_name=new_job.folder_path,
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
                run_id=new_job.pk,
                team_id=team.id,
            ),
        )

        assert mock_get_columns.call_count == 10


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_validate_schema_and_update_table_activity_failed(activity_environment, team, **kwargs):
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
        mock_get_columns.side_effect = Exception("test")

        with pytest.raises(Exception):
            await activity_environment.run(
                validate_schema_activity,
                ValidateSchemaInputs(
                    run_id=new_job.pk,
                    team_id=team.id,
                ),
            )

        assert mock_get_columns.call_count == 1


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
                run_id=new_job.pk,
                team_id=team.id,
            ),
        )

        assert mock_get_columns.call_count == 10
        all_tables = DataWarehouseTable.objects.all()
        table_length = await sync_to_async(len)(all_tables)  # type: ignore
        assert table_length == 5

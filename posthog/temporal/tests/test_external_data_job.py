import pytest
from asgiref.sync import sync_to_async
import uuid
from unittest import mock

from posthog.warehouse.models import ExternalDataJob, ExternalDataSource

from posthog.warehouse.data_load.pipeline import StripeJobInputs
from posthog.warehouse.data_load.service import ExternalDataJobInputs

from posthog.temporal.workflows.external_data_job import (
    create_external_data_job_model,
    CreateExternalDataJobInputs,
    UpdateExternalDataJobStatusInputs,
    update_external_data_job_model,
    create_external_data_job,
    run_external_data_job,
    ExternalDataJobWorkflow,
)

from temporalio.client import Client
from temporalio.worker import UnsandboxedWorkflowRunner, Worker
from django.conf import settings


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_external_job_activity(activity_environment, team, **kwargs):
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
    )

    inputs = CreateExternalDataJobInputs(team_id=team.id, external_data_source_id=new_source.pk)

    run_id = await activity_environment.run(create_external_data_job_model, inputs)

    runs = ExternalDataJob.objects.filter(id=run_id)
    assert await sync_to_async(runs.exists)()  # type:ignore


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_external_job_activity(activity_environment, team, **kwargs):
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
    )

    new_job = await sync_to_async(create_external_data_job)(team_id=team.id, external_data_source_id=new_source.pk)

    inputs = UpdateExternalDataJobStatusInputs(
        id=str(new_job.id), run_id=str(new_job.id), status=ExternalDataJob.Status.COMPLETED, latest_error=None
    )

    await activity_environment.run(update_external_data_job_model, inputs)
    await sync_to_async(new_job.refresh_from_db)()

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
    )

    inputs = ExternalDataJobInputs(team_id=team.id, external_data_source_id=new_source.pk)

    with mock.patch(
        "posthog.warehouse.data_load.pipeline.create_pipeline",
    ) as mock_create_pipeline, mock.patch(
        "posthog.warehouse.data_load.pipeline.stripe_source",
    ) as mock_run_stripe:
        await activity_environment.run(run_external_data_job, inputs)
        mock_create_pipeline.assert_called_once_with(
            StripeJobInputs(
                job_type="Stripe",
                team_id=team.id,
                stripe_secret_key="test-key",
            )
        )
        mock_run_stripe.assert_called_once_with(stripe_secret_key="test-key")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_external_data_job_workflow(team):
    """Test the squash_person_overrides workflow end-to-end with newer overrides."""
    client = await Client.connect(
        f"{settings.TEMPORAL_HOST}:{settings.TEMPORAL_PORT}",
        namespace=settings.TEMPORAL_NAMESPACE,
    )

    workflow_id = str(uuid.uuid4())

    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key"},
    )

    inputs = ExternalDataJobInputs(team_id=team.id, external_data_source_id=new_source.pk)

    async with Worker(
        client,
        task_queue=settings.TEMPORAL_EXTERNAL_DATA_JOB_TASK_QUEUE,
        workflows=[ExternalDataJobWorkflow],
        activities=[
            create_external_data_job_model,
            run_external_data_job,
            update_external_data_job_model,
        ],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        with mock.patch(
            "posthog.warehouse.data_load.pipeline.create_pipeline",
        ) as mock_create_pipeline, mock.patch(
            "posthog.warehouse.data_load.pipeline.stripe_source",
        ) as mock_run_stripe:
            await client.execute_workflow(
                ExternalDataJobWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.TEMPORAL_EXTERNAL_DATA_JOB_TASK_QUEUE,
            )
            mock_create_pipeline.assert_called_once_with(
                StripeJobInputs(
                    job_type="Stripe",
                    team_id=team.id,
                    stripe_secret_key="test-key",
                )
            )
            mock_run_stripe.assert_called_once_with(stripe_secret_key="test-key")

            new_job = await sync_to_async(ExternalDataJob.objects.first)()

            assert new_job.status == ExternalDataJob.Status.COMPLETED

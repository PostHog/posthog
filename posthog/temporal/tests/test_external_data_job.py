import uuid
from unittest import mock

import pytest
from asgiref.sync import sync_to_async
from django.conf import settings
from django.test import override_settings
from temporalio.client import Client
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.data_imports.external_data_job import (
    CreateExternalDataJobInputs,
    ExternalDataJobWorkflow,
    UpdateExternalDataJobStatusInputs,
    ValidateSchemaInputs,
    create_external_data_job,
    create_external_data_job_model,
    move_draft_to_production_activity,
    run_external_data_job,
    update_external_data_job_model,
    validate_schema_activity,
)
from posthog.warehouse.data_load.pipeline import (
    SourceColumnType,
    SourceSchema,
    StripeJobInputs,
)
from posthog.warehouse.data_load.service import ExternalDataJobInputs
from posthog.warehouse.data_load.stripe import ENDPOINTS
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
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
    )  # type: ignore

    new_job = await sync_to_async(create_external_data_job)(team_id=team.id, external_data_source_id=new_source.pk)  # type: ignore

    inputs = UpdateExternalDataJobStatusInputs(
        id=str(new_job.id), run_id=str(new_job.id), status=ExternalDataJob.Status.COMPLETED, latest_error=None
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

    inputs = ExternalDataJobInputs(team_id=team.id, external_data_source_id=new_source.pk)

    with mock.patch(
        "posthog.warehouse.data_load.pipeline.create_pipeline",
    ) as mock_create_pipeline, mock.patch(
        "posthog.warehouse.data_load.pipeline.stripe_source",
    ) as mock_run_stripe, mock.patch(
        "posthog.warehouse.data_load.pipeline.get_schema",
    ) as mock_data_tables:
        mock_data_tables.return_value = [
            SourceSchema(
                resource="customers",
                name="customers",
                columns={
                    "id": SourceColumnType(name="id", data_type="string", nullable=False),
                    "name": SourceColumnType(name="name", data_type="string", nullable=True),
                },
                write_disposition="overwrite",
            )
        ]
        schemas = await activity_environment.run(run_external_data_job, inputs)
        mock_create_pipeline.assert_called_once_with(
            StripeJobInputs(
                job_type="Stripe",
                team_id=team.id,
                stripe_secret_key="test-key",
                dataset_name=new_source.draft_folder_path,
            )
        )
        mock_run_stripe.assert_called_once_with(stripe_secret_key="test-key", endpoints=ENDPOINTS)
        assert len(schemas) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_is_schema_valid_activity(activity_environment, team, **kwargs):
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key"},
    )  # type: ignore

    with mock.patch(
        "posthog.warehouse.models.table.DataWarehouseTable.get_columns"
    ) as mock_get_columns, override_settings(**AWS_BUCKET_MOCK_SETTINGS):
        mock_get_columns.return_value = {"id": "string"}
        await activity_environment.run(
            validate_schema_activity,
            ValidateSchemaInputs(
                external_data_source_id=new_source.pk,
                source_schemas=[
                    SourceSchema(
                        resource="customers",
                        name="customers",
                        columns={
                            "id": SourceColumnType(name="id", data_type="string", nullable=False),
                            "name": SourceColumnType(name="name", data_type="string", nullable=True),
                        },
                        write_disposition="overwrite",
                    )
                ],
                create=False,
            ),
        )

        assert mock_get_columns.call_count == 5


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_is_schema_valid_activity_failed(activity_environment, team, **kwargs):
    new_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key"},
    )  # type: ignore

    with mock.patch(
        "posthog.warehouse.models.table.DataWarehouseTable.get_columns"
    ) as mock_get_columns, override_settings(**AWS_BUCKET_MOCK_SETTINGS):
        mock_get_columns.return_value = {"id": "string"}
        mock_get_columns.side_effect = Exception("test")

        with pytest.raises(Exception):
            await activity_environment.run(
                validate_schema_activity,
                ValidateSchemaInputs(
                    external_data_source_id=new_source.pk,
                    source_schemas=[
                        SourceSchema(
                            resource="customers",
                            name="customers",
                            columns={
                                "id": SourceColumnType(name="id", data_type="string", nullable=False),
                                "name": SourceColumnType(name="name", data_type="string", nullable=True),
                            },
                            write_disposition="overwrite",
                        )
                    ],
                    create=False,
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

    with mock.patch(
        "posthog.warehouse.models.table.DataWarehouseTable.get_columns"
    ) as mock_get_columns, override_settings(**AWS_BUCKET_MOCK_SETTINGS):
        mock_get_columns.return_value = {"id": "string"}
        await activity_environment.run(
            validate_schema_activity,
            ValidateSchemaInputs(
                external_data_source_id=new_source.pk,
                source_schemas=[
                    SourceSchema(
                        resource="customers",
                        name="customers",
                        columns={
                            "id": SourceColumnType(name="id", data_type="string", nullable=False),
                            "name": SourceColumnType(name="name", data_type="string", nullable=True),
                        },
                        write_disposition="overwrite",
                    )
                ],
                create=True,
            ),
        )

        assert mock_get_columns.call_count == 5
        all_tables = DataWarehouseTable.objects.all()
        table_length = await sync_to_async(len)(all_tables)  # type: ignore
        assert table_length == 5

        # Should still have one after
        await activity_environment.run(
            validate_schema_activity,
            ValidateSchemaInputs(
                external_data_source_id=new_source.pk,
                source_schemas=[
                    SourceSchema(
                        resource="customers",
                        name="customers",
                        columns={
                            "id": SourceColumnType(name="id", data_type="string", nullable=False),
                            "name": SourceColumnType(name="name", data_type="string", nullable=True),
                        },
                        write_disposition="overwrite",
                    )
                ],
                create=True,
            ),
        )

        all_tables = DataWarehouseTable.objects.all()
        table_length = await sync_to_async(len)(all_tables)  # type: ignore

        assert table_length == 5


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
    )  # type: ignore

    inputs = ExternalDataJobInputs(team_id=team.id, external_data_source_id=new_source.pk)

    async with Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[ExternalDataJobWorkflow],
        activities=[
            create_external_data_job_model,
            run_external_data_job,
            update_external_data_job_model,
            move_draft_to_production_activity,
            validate_schema_activity,
        ],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        # TODO: don't need to test all the activities here, just the workflow
        with mock.patch(
            "posthog.warehouse.data_load.pipeline.create_pipeline",
        ) as mock_create_pipeline, mock.patch(
            "posthog.warehouse.data_load.pipeline.stripe_source",
        ) as mock_run_stripe, mock.patch(
            "posthog.warehouse.data_load.pipeline.get_schema",
        ) as mock_data_tables, mock.patch(
            "posthog.warehouse.models.table.DataWarehouseTable.get_columns"
        ) as mock_get_columns, mock.patch(
            "posthog.temporal.data_imports.external_data_job.move_draft_to_production"
        ) as mock_move_draft_to_production, override_settings(**AWS_BUCKET_MOCK_SETTINGS):
            mock_get_columns.return_value = {"id": "string"}
            mock_data_tables.return_value = [
                SourceSchema(
                    resource="customers",
                    name="customers",
                    columns={
                        "id": SourceColumnType(name="id", data_type="string", nullable=False),
                        "name": SourceColumnType(name="name", data_type="string", nullable=True),
                    },
                    write_disposition="overwrite",
                )
            ]

            await client.execute_workflow(
                ExternalDataJobWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )
            mock_create_pipeline.assert_called_once_with(
                StripeJobInputs(
                    job_type="Stripe",
                    team_id=team.id,
                    stripe_secret_key="test-key",
                    dataset_name=new_source.draft_folder_path,
                )
            )
            mock_run_stripe.assert_called_once_with(stripe_secret_key="test-key", endpoints=ENDPOINTS)

            assert mock_get_columns.call_count == 10

            all_tables = DataWarehouseTable.objects.all()
            table_length = await sync_to_async(len)(all_tables)  # type: ignore

            assert table_length == 5

            assert mock_move_draft_to_production.call_count == 1

            new_job = await sync_to_async(ExternalDataJob.objects.first)()  # type: ignore
            assert new_job.status == ExternalDataJob.Status.COMPLETED

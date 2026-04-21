import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest import mock
from unittest.mock import AsyncMock

from django.conf import settings
from django.test import override_settings

from asgiref.sync import async_to_sync
from dlt.common.configuration.specs.aws_credentials import AwsCredentials
from rest_framework.test import APIClient
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.data_imports.external_data_job import ExternalDataJobWorkflow
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
from posthog.temporal.data_imports.settings import ACTIVITIES
from posthog.temporal.data_imports.sources.stripe.constants import (
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
)
from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.data_warehouse.backend.models import ExternalDataSchema, ExternalDataSource
from products.data_warehouse.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.external_data_job import ExternalDataJob, get_latest_run_if_exists
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind

BUCKET_NAME = "test-pipeline"


@pytest.fixture
def api_client(user):
    client = APIClient()
    client.force_login(user)

    with (
        mock.patch(
            "posthog.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
            return_value=(True, None),
        ),
        mock.patch(
            "products.data_warehouse.backend.api.external_data_source.sync_external_data_job_workflow",
        ) as mock_sync_workflow,
        mock.patch.object(DataWarehouseSavedQuery, "schedule_materialization"),
    ):
        client.captured_sync_workflow = mock_sync_workflow  # type: ignore[attr-defined]
        yield client


@pytest.fixture
def run_data_import_workflow(mock_stripe_client):
    """Fixture that provides a function to run a data import workflow synchronously.

    Sets up all the mocks needed for the Temporal workflow to execute against
    local MinIO storage with mock Stripe data. The mock_stripe_client fixture
    provides the mocked Stripe API responses.
    """

    def _mock_to_session_credentials(self):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def _mock_to_object_store_rs_credentials(self):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    async def _run(team, source: ExternalDataSource, schema: ExternalDataSchema):
        inputs = ExternalDataWorkflowInputs(
            team_id=team.id,
            external_data_source_id=source.pk,
            external_data_schema_id=schema.id,
            billable=False,
        )

        with (
            mock.patch.object(DeltaTableHelper, "compact_table"),
            mock.patch("posthog.temporal.data_imports.external_data_job.get_data_import_finished_metric"),
            mock.patch("posthoganalytics.capture_exception", return_value=None),
            mock.patch.object(DataWarehouseSavedQuery, "schedule_materialization"),
            mock.patch(
                "posthog.temporal.data_imports.workflow_activities.import_data_sync._is_pipeline_v3_enabled",
                new_callable=AsyncMock,
                return_value=False,
            ),
            mock.patch.object(AwsCredentials, "to_session_credentials", _mock_to_session_credentials),
            mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", _mock_to_object_store_rs_credentials),
            override_settings(
                BUCKET_URL=f"s3://{BUCKET_NAME}",
                BUCKET_PATH=BUCKET_NAME,
                DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
                DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
                DATA_WAREHOUSE_REDIS_HOST="localhost",
                DATA_WAREHOUSE_REDIS_PORT="6379",
                DATAWAREHOUSE_BUCKET=BUCKET_NAME,
            ),
        ):
            async with await WorkflowEnvironment.start_time_skipping() as env:
                async with Worker(
                    env.client,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    workflows=[ExternalDataJobWorkflow],
                    activities=ACTIVITIES,  # type: ignore
                    workflow_runner=UnsandboxedWorkflowRunner(),
                    activity_executor=ThreadPoolExecutor(max_workers=50),
                    max_concurrent_activities=50,
                ):
                    await env.client.execute_workflow(
                        ExternalDataJobWorkflow.run,
                        inputs,
                        id=str(uuid.uuid4()),
                        task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

        run = await get_latest_run_if_exists(team_id=team.pk, pipeline_id=source.pk)
        assert run is not None
        assert run.status == ExternalDataJob.Status.COMPLETED, f"Workflow failed: {run.latest_error}"

    return async_to_sync(_run)


def _is_empty_query(query: DataWarehouseSavedQuery) -> bool:
    assert query.query is not None
    return "where false" in query.query.get("query", "").lower()


@pytest.mark.django_db(transaction=True)
def test_stripe_source_creation_and_sync_updates_managed_views(team, api_client, run_data_import_workflow):
    response = api_client.post(
        f"/api/environments/{team.pk}/external_data_sources/",
        data={
            "source_type": "Stripe",
            "payload": {
                "auth_method": {
                    "selection": "api_key",
                    "stripe_secret_key": "sk_test_123",
                },
                "schemas": [
                    {"name": STRIPE_SUBSCRIPTION_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                ],
            },
        },
    )
    assert response.status_code == 201, f"API create failed: {response.json()}"

    source = ExternalDataSource.objects.get(pk=response.json()["id"])
    managed_viewset = DataWarehouseManagedViewSet.objects.filter(
        team=team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
    ).first()
    assert managed_viewset is not None
    saved_query = DataWarehouseSavedQuery.objects.get(
        team=team, managed_viewset=managed_viewset, name="stripe.subscription_revenue_view"
    )
    assert _is_empty_query(saved_query), f"{saved_query.name} view should have an empty query before sync"
    schema = ExternalDataSchema.objects.get(source=source, name=STRIPE_SUBSCRIPTION_RESOURCE_NAME)

    run_data_import_workflow(team, source, schema)

    schema.refresh_from_db()
    saved_query.refresh_from_db()
    assert schema.table is not None, "Workflow should have created the table"
    assert not _is_empty_query(saved_query), f"{saved_query.name} still has an empty query"

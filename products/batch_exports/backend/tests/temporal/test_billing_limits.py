"""Tests for billing limit enforcement across batch export workflows.

The `start_batch_export_run` activity raises `OverBillingLimitError` when a team
is over its rows exported billing limit. Temporal does not propagate the original
exception class to the workflow: the workflow sees a `temporalio.exceptions.ActivityError`
whose cause is an `ApplicationError` with `type == "OverBillingLimitError"`. These
tests assert both the propagation semantics and that every destination workflow
handles the error by finishing cleanly, leaving behind a run with 'FailedBilling'
status.
"""

import uuid
import datetime as dt

import pytest
import unittest.mock

from django.conf import settings
from django.test import override_settings

from temporalio import exceptions, workflow
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.tests.utils.models import afetch_batch_export_runs

from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination, BatchExportRun
from products.batch_exports.backend.service import (
    AzureBlobBatchExportInputs,
    BigQueryBatchExportInputs,
    DatabricksBatchExportInputs,
    PostgresBatchExportInputs,
    RedshiftBatchExportInputs,
    S3BatchExportInputs,
    SnowflakeBatchExportInputs,
)
from products.batch_exports.backend.temporal.batch_exports import (
    StartBatchExportRunInputs,
    is_over_billing_limit_error,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.destinations.azure_blob_batch_export import AzureBlobBatchExportWorkflow
from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import BigQueryBatchExportWorkflow
from products.batch_exports.backend.temporal.destinations.databricks_batch_export import DatabricksBatchExportWorkflow
from products.batch_exports.backend.temporal.destinations.postgres_batch_export import PostgresBatchExportWorkflow
from products.batch_exports.backend.temporal.destinations.redshift_batch_export import RedshiftBatchExportWorkflow
from products.batch_exports.backend.temporal.destinations.s3_batch_export import S3BatchExportWorkflow
from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import SnowflakeBatchExportWorkflow

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db(transaction=True),
]

TEST_TIME = dt.datetime(2025, 4, 24, 1, 0, 0, tzinfo=dt.UTC)


@pytest.fixture
def batch_export(team):
    destination = BatchExportDestination.objects.create(type="S3", config={})
    batch_export = BatchExport.objects.create(
        name="billing-limit-test-export", team=team, destination=destination, interval="hour"
    )

    yield batch_export

    batch_export.delete()
    destination.delete()


@pytest.fixture
def over_billing_limit():
    """Report any team as over its rows exported billing limit."""
    with (
        override_settings(BATCH_EXPORTS_ENABLE_BILLING_CHECK=True),
        unittest.mock.patch(
            "products.batch_exports.backend.temporal.batch_exports.check_is_over_limit",
            new=unittest.mock.AsyncMock(return_value=True),
        ) as mock,
    ):
        yield mock


@workflow.defn(name="billing-limit-test-reraise")
class ReRaiseBillingLimitTestWorkflow:
    """Workflow calling 'start_batch_export_run' without handling any errors."""

    @workflow.run
    async def run(self, inputs: StartBatchExportRunInputs) -> str:
        return await workflow.execute_activity(
            start_batch_export_run,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=RetryPolicy(
                maximum_attempts=1,
                non_retryable_error_types=["OverBillingLimitError"],
            ),
        )


@workflow.defn(name="billing-limit-test-catch")
class CatchBillingLimitTestWorkflow:
    """Workflow calling 'start_batch_export_run' handling billing limit errors."""

    @workflow.run
    async def run(self, inputs: StartBatchExportRunInputs) -> str:
        try:
            return await workflow.execute_activity(
                start_batch_export_run,
                inputs,
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    maximum_attempts=1,
                    non_retryable_error_types=["OverBillingLimitError"],
                ),
            )
        except exceptions.ActivityError as e:
            if is_over_billing_limit_error(e):
                return "over-billing-limit"
            raise


async def _execute_test_workflow(workflow_class, inputs):
    workflow_id = str(uuid.uuid4())

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[workflow_class],
            activities=[start_batch_export_run],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                workflow_class.run,
                inputs,
                id=workflow_id,
                task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(minutes=1),
            )


async def test_over_billing_limit_error_propagates_as_activity_error(team, batch_export, over_billing_limit):
    """Test the exception a workflow actually sees when the activity raises 'OverBillingLimitError'.

    Temporal wraps activity exceptions, so a workflow can never catch 'OverBillingLimitError'
    directly: it must inspect the 'ActivityError' cause.
    """
    inputs = StartBatchExportRunInputs(
        team_id=team.id,
        batch_export_id=str(batch_export.id),
        data_interval_start=(TEST_TIME - dt.timedelta(hours=1)).isoformat(),
        data_interval_end=TEST_TIME.isoformat(),
    )

    with pytest.raises(WorkflowFailureError) as exc_info:
        await _execute_test_workflow(ReRaiseBillingLimitTestWorkflow, inputs)

    activity_error = exc_info.value.cause
    assert isinstance(activity_error, exceptions.ActivityError)
    assert isinstance(activity_error.cause, exceptions.ApplicationError)
    assert activity_error.cause.type == "OverBillingLimitError"
    assert is_over_billing_limit_error(activity_error)

    runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
    assert len(runs) == 1
    assert runs[0].status == BatchExportRun.Status.FAILED_BILLING


async def test_over_billing_limit_error_is_caught_by_workflow(team, batch_export, over_billing_limit):
    """Test a workflow can catch the billing limit error and finish cleanly."""
    inputs = StartBatchExportRunInputs(
        team_id=team.id,
        batch_export_id=str(batch_export.id),
        data_interval_start=(TEST_TIME - dt.timedelta(hours=1)).isoformat(),
        data_interval_end=TEST_TIME.isoformat(),
    )

    result = await _execute_test_workflow(CatchBillingLimitTestWorkflow, inputs)

    assert result == "over-billing-limit"

    runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
    assert len(runs) == 1
    assert runs[0].status == BatchExportRun.Status.FAILED_BILLING


@pytest.mark.parametrize(
    "workflow_class,inputs_class,destination_config",
    [
        (
            S3BatchExportWorkflow,
            S3BatchExportInputs,
            {"bucket_name": "a-bucket", "region": "us-east-1", "prefix": "a-prefix"},
        ),
        (BigQueryBatchExportWorkflow, BigQueryBatchExportInputs, {"dataset_id": "a-dataset"}),
        (
            SnowflakeBatchExportWorkflow,
            SnowflakeBatchExportInputs,
            {"database": "a-database", "warehouse": "a-warehouse", "schema": "a-schema"},
        ),
        (PostgresBatchExportWorkflow, PostgresBatchExportInputs, {"database": "a-database"}),
        (
            RedshiftBatchExportWorkflow,
            RedshiftBatchExportInputs,
            {"user": "a-user", "password": "a-password", "host": "a-host", "database": "a-database"},
        ),
        (AzureBlobBatchExportWorkflow, AzureBlobBatchExportInputs, {"container_name": "a-container"}),
        (
            DatabricksBatchExportWorkflow,
            DatabricksBatchExportInputs,
            {"http_path": "a-path", "catalog": "a-catalog", "schema": "a-schema", "table_name": "a-table"},
        ),
    ],
)
async def test_destination_workflow_finishes_cleanly_when_over_billing_limit(
    team,
    batch_export,
    over_billing_limit,
    workflow_class,
    inputs_class,
    destination_config,
):
    """Test destination workflows handle a team over its billing limit.

    The workflow must finish without failing, without running any export activity,
    and leave behind a run with 'FailedBilling' status.
    """
    inputs = inputs_class(
        team_id=team.id,
        batch_export_id=str(batch_export.id),
        interval="hour",
        data_interval_end=TEST_TIME.isoformat(),
        **destination_config,
    )

    await _execute_test_workflow(workflow_class, inputs)

    runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
    assert len(runs) == 1
    assert runs[0].status == BatchExportRun.Status.FAILED_BILLING

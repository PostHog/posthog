import json
import uuid
import datetime as dt
from dataclasses import dataclass

import pytest

from django.conf import settings

from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.batch_exports.service import BaseBatchExportInputs, BatchExportInsertInputs, BatchExportModel
from posthog.models import BatchExport, BatchExportDestination
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.tests.utils.models import afetch_batch_export_runs

from products.batch_exports.backend.temporal.batch_exports import (
    StartBatchExportRunInputs,
    finish_batch_export_run,
    get_data_interval,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.pipeline.entrypoint import execute_batch_export_using_internal_stage
from products.batch_exports.backend.temporal.pipeline.internal_stage import insert_into_internal_stage_activity
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.utils import handle_non_retryable_errors

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


@pytest.fixture
async def batch_export(
    ateam,
    # temporal_client,
):
    """Provide a batch export for tests, not intended to be used."""
    destination_data = {"type": "Dummy", "config": {}}

    destination = await BatchExportDestination.objects.acreate(**destination_data)

    batch_export = await BatchExport.objects.acreate(
        team=ateam,
        name="test-batch-export",
        destination=destination,
        interval="hour",
    )

    yield batch_export

    await batch_export.adelete()
    await destination.adelete()


class DummyNonRetryableError(Exception):
    def __init__(self, message: str = "This is a user error"):
        super().__init__(message)


class DummyRetryableError(Exception):
    def __init__(self, message: str = "This is an unexpected internal error"):
        super().__init__(message)


NON_RETRYABLE_ERROR_TYPES = ("DummyNonRetryableError",)


@dataclass(kw_only=True)
class DummyExportInputs(BaseBatchExportInputs):
    """Inputs for the Dummy export workflow."""

    exception_to_raise: str | None = None


@dataclass(kw_only=True)
class DummyInsertInputs(BatchExportInsertInputs):
    """Inputs for the Dummy insert activity."""

    exception_to_raise: str | None = None


@workflow.defn(name="dummy-export", failure_exception_types=[workflow.NondeterminismError])
class DummyExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow for testing the batch export entrypoint."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> DummyExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return DummyExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: DummyExportInputs):
        """Workflow implementation to test the batch export entrypoint."""
        is_backfill = inputs.get_is_backfill()
        is_earliest_backfill = inputs.get_is_earliest_backfill()
        data_interval_start, data_interval_end = get_data_interval(inputs.interval, inputs.data_interval_end)
        should_backfill_from_beginning = is_backfill and is_earliest_backfill

        start_batch_export_run_inputs = StartBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            backfill_id=inputs.backfill_details.backfill_id if inputs.backfill_details else None,
        )
        run_id = await workflow.execute_activity(
            start_batch_export_run,
            start_batch_export_run_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )

        insert_inputs = DummyInsertInputs(
            team_id=inputs.team_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            run_id=run_id,
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
            batch_export_model=inputs.batch_export_model,
            # TODO: Remove after updating existing batch exports.
            batch_export_schema=inputs.batch_export_schema,
            batch_export_id=inputs.batch_export_id,
            destination_default_fields=None,
            exception_to_raise=inputs.exception_to_raise,
        )

        await execute_batch_export_using_internal_stage(
            insert_into_dummy_activity_from_stage,
            insert_inputs,
            interval=inputs.interval,
        )
        return


@activity.defn(name="insert_into_dummy_activity_from_stage")
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_dummy_activity_from_stage(inputs: DummyInsertInputs) -> BatchExportResult:
    """A mock activity to test the batch export entrypoint."""
    if inputs.exception_to_raise:
        # get the exception class from the string
        exception_cls = globals()[inputs.exception_to_raise]
        raise exception_cls()
    return BatchExportResult(records_completed=100, bytes_exported=100)


class TestErrorHandling:
    async def _run_workflow(self, inputs: DummyExportInputs, expect_workflow_failure: bool = True):
        workflow_id = str(uuid.uuid4())

        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[DummyExportWorkflow],
                activities=[
                    start_batch_export_run,
                    finish_batch_export_run,
                    insert_into_internal_stage_activity,
                    insert_into_dummy_activity_from_stage,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                # we expect the workflow to fail because of the non-retryable error
                if expect_workflow_failure:
                    with pytest.raises(WorkflowFailureError):
                        await activity_environment.client.execute_workflow(
                            DummyExportWorkflow.run,
                            inputs,
                            id=workflow_id,
                            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                            retry_policy=RetryPolicy(maximum_attempts=1),
                            execution_timeout=dt.timedelta(minutes=1),
                        )
                else:
                    await activity_environment.client.execute_workflow(
                        DummyExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                        execution_timeout=dt.timedelta(minutes=1),
                    )

        runs = await afetch_batch_export_runs(batch_export_id=uuid.UUID(inputs.batch_export_id))
        assert len(runs) == 1
        run = runs[0]
        return run

    async def test_handling_of_non_retryable_errors(self, batch_export):
        """A non-retryable error raised by an 'insert-into-destination' activity should result in a failed batch export
        run but a successful Temporal activity. This is because we treat this error as an 'expected' user error which
        could be caused by things such as invalid credentials or permissions.
        """
        inputs = DummyExportInputs(
            team_id=batch_export.team_id,
            batch_export_id=str(batch_export.id),
            interval="hour",
            data_interval_end=dt.datetime(2025, 7, 21, 13, 0, 0, tzinfo=dt.UTC).isoformat(),
            batch_export_model=BatchExportModel(name="events", schema=None),
            exception_to_raise="DummyNonRetryableError",
        )
        run = await self._run_workflow(inputs, expect_workflow_failure=False)
        assert run.status == "Failed"
        assert run.latest_error == "DummyNonRetryableError: This is a user error"

    async def test_handling_of_retryable_errors(self, batch_export):
        """A retryable error raised by an 'insert-into-destination' activity should result in a failed batch export
        run and a failed Temporal activity. This is because we treat this error as an 'unexpected' internal error
        which could be caused by things such as a temporary network issue or a bug in the code.
        """
        inputs = DummyExportInputs(
            team_id=batch_export.team_id,
            batch_export_id=str(batch_export.id),
            interval="hour",
            data_interval_end=dt.datetime(2025, 7, 21, 13, 0, 0, tzinfo=dt.UTC).isoformat(),
            batch_export_model=BatchExportModel(name="events", schema=None),
            exception_to_raise="DummyRetryableError",
        )
        run = await self._run_workflow(inputs, expect_workflow_failure=True)
        assert run.status == "FailedRetryable"
        assert run.latest_error == "DummyRetryableError: This is an unexpected internal error"

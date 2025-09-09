"""Base test framework for batch export destinations.

This module provides a common test interface that can be implemented by each
destination to ensure consistent behavior and error handling across all destinations.
"""

import uuid
import asyncio
import datetime as dt
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable
from typing import Any, Optional, Union

import pytest

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog import constants
from posthog.batch_exports.models import BatchExport
from posthog.batch_exports.service import BackfillDetails, BatchExportModel, BatchExportSchema
from posthog.models.team import Team
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export, afetch_batch_export_runs

from products.batch_exports.backend.temporal.batch_exports import finish_batch_export_run, start_batch_export_run
from products.batch_exports.backend.temporal.pipeline.internal_stage import insert_into_internal_stage_activity
from products.batch_exports.backend.tests.temporal.utils import mocked_start_batch_export_run


class BaseDestinationTest(ABC):
    """Base class for destination-specific tests.

    Each destination test class should inherit from this and implement the abstract methods
    to define destination-specific behavior while inheriting common test patterns.
    """

    @property
    @abstractmethod
    def destination_type(self) -> str:
        """Return the destination type name (e.g., 'Databricks', 'S3', 'BigQuery')."""
        pass

    @property
    @abstractmethod
    def workflow_class(self) -> type:
        """Return the workflow class for this destination."""
        pass

    @property
    @abstractmethod
    def main_activity(self) -> Callable:
        """Return the main 'insert_into_*' activity for this destination."""
        pass

    @property
    @abstractmethod
    def batch_export_inputs_class(self) -> type:
        """Return the inputs dataclass for the batch export workflow."""
        pass

    def create_batch_export_inputs(
        self,
        team_id: int,
        batch_export_id: str,
        data_interval_end: dt.datetime,
        interval: str,
        batch_export_model: Optional[BatchExportModel] = None,
        batch_export_schema: Optional[BatchExportSchema] = None,
        backfill_details: Optional[BackfillDetails] = None,
        **config,
    ) -> Any:
        """Create workflow inputs for the destination."""
        return self.batch_export_inputs_class(
            team_id=team_id,
            batch_export_id=batch_export_id,
            data_interval_end=data_interval_end,
            interval=interval,
            batch_export_model=batch_export_model,
            batch_export_schema=batch_export_schema,
            backfill_details=backfill_details,
            **config,
        )

    @abstractmethod
    def get_destination_config(self, team_id: int) -> dict:
        """Return the destination configuration."""
        pass

    @abstractmethod
    async def assert_data_in_destination(
        self,
        team_id: int,
        data_interval_start: dt.datetime,
        data_interval_end: dt.datetime,
        exclude_events: Optional[list[str]] = None,
        batch_export_model: Optional[Union[BatchExportModel, BatchExportSchema]] = None,
        **kwargs,
    ) -> None:
        """Assert that the expected data was written to the destination."""
        pass

    @abstractmethod
    async def assert_no_data_in_destination(self, **kwargs) -> None:
        """Assert that no data was written to the destination."""
        pass

    @abstractmethod
    async def setup_destination_for_test(self) -> None:
        """Setup the destination for the test.

        For example, create any resources that are needed for the test (e.g. the database, S3 bucket, etc).
        """
        pass

    @abstractmethod
    async def teardown_destination_for_test(self) -> None:
        """Teardown the destination for the test.

        Cleanup any resources that were created for the test (e.g. the database, S3 bucket, etc).
        """
        pass


class CommonDestinationTests:
    """Common test patterns for all batch export destinations.

    This class provides reusable test methods that work across all destinations
    by using the abstract interface defined in BaseDestinationTest.
    """

    # Common test models used across destinations
    TEST_MODELS = [
        BatchExportModel(
            name="a-custom-model",
            schema={
                "fields": [
                    {"expression": "uuid", "alias": "uuid"},
                    {"expression": "event", "alias": "my_event_name"},
                    {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
                    {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
                    {"expression": "nullIf(properties, '')", "alias": "all_properties"},
                ],
                "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
            },
        ),
        BatchExportModel(name="events", schema=None),
        BatchExportModel(
            name="events",
            schema=None,
            filters=[
                {"key": "$browser", "operator": "exact", "type": "event", "value": ["Chrome"]},
                {"key": "$os", "operator": "exact", "type": "event", "value": ["Mac OS X"]},
            ],
        ),
        BatchExportModel(name="persons", schema=None),
        BatchExportModel(name="sessions", schema=None),
        {
            "fields": [
                {"expression": "uuid", "alias": "uuid"},
                {"expression": "event", "alias": "my_event_name"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
                {"expression": "nullIf(properties, '')", "alias": "all_properties"},
            ],
            "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
        },
        None,
    ]

    @pytest.fixture
    def destination_data(self, destination_test, ateam, exclude_events):
        """Provide test configuration for destination."""
        destination_config = destination_test.get_destination_config(ateam.pk)
        destination_data = {
            "type": destination_test.destination_type,
            "config": {
                **destination_config,
                "exclude_events": exclude_events,
            },
        }
        return destination_data

    @pytest.fixture
    async def batch_export_for_destination(self, ateam, destination_data, temporal_client, interval):
        """Manage BatchExport model (and associated Temporal Schedule) for tests"""
        batch_export_data = {
            "name": "my-production-snowflake-export",
            "destination": destination_data,
            "interval": interval,
        }

        batch_export = await acreate_batch_export(
            team_id=ateam.pk,
            name=batch_export_data["name"],
            destination_data=batch_export_data["destination"],
            interval=batch_export_data["interval"],
        )

        yield batch_export

        await adelete_batch_export(batch_export, temporal_client)

    @pytest.fixture
    async def setup_destination(self, destination_test: BaseDestinationTest) -> AsyncGenerator[None, None]:
        """Setup the destination for the test."""
        await destination_test.setup_destination_for_test()
        yield
        await destination_test.teardown_destination_for_test()

    async def _run_workflow(
        self,
        destination_test: BaseDestinationTest,
        batch_export_for_destination: BatchExport,
        team: Team,
        data_interval_end,
        interval: str,
        batch_export_model: BatchExportModel | None = None,
        batch_export_schema: BatchExportSchema | None = None,
        backfill_details=None,
    ):
        """Helper function to run SnowflakeBatchExportWorkflow and assert records in Snowflake"""
        workflow_id = str(uuid.uuid4())
        inputs = destination_test.create_batch_export_inputs(
            team_id=team.pk,
            batch_export_id=str(batch_export_for_destination.id),
            data_interval_end=data_interval_end.isoformat(),
            interval=interval,
            batch_export_schema=batch_export_schema,
            batch_export_model=batch_export_model,
            backfill_details=backfill_details,
            **batch_export_for_destination.destination.config,
        )

        # settings_overrides = settings_overrides or {}
        # if use_internal_stage:
        #     settings_overrides["BATCH_EXPORT_SNOWFLAKE_USE_STAGE_TEAM_IDS"] = [team.pk]

        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[destination_test.workflow_class],
                activities=[
                    start_batch_export_run,
                    insert_into_internal_stage_activity,
                    destination_test.main_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await activity_environment.client.execute_workflow(
                    destination_test.workflow_class.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(minutes=5),
                )

        runs = await afetch_batch_export_runs(batch_export_id=batch_export_for_destination.id)
        assert len(runs) == 1

        run = runs[0]
        return run

    @pytest.mark.parametrize("interval", ["hour"], indirect=True)
    @pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
    @pytest.mark.parametrize("model", TEST_MODELS)
    async def test_workflow_completes_successfully(
        self,
        destination_test: BaseDestinationTest,
        interval: str,
        exclude_events: Optional[list[str]],
        model: Union[BatchExportModel, BatchExportSchema, None],
        generate_test_data,
        data_interval_start: dt.datetime,
        data_interval_end: dt.datetime,
        ateam,
        batch_export_for_destination,  # This fixture needs to be provided by destination-specific tests
    ):
        """Test that the workflow completes successfully end-to-end.

        We test this for all models using a single interval.
        """
        if isinstance(model, BatchExportModel) and model.name != "events" and exclude_events is not None:
            pytest.skip(
                f"Unnecessary test case as batch export model '{model.name}' is not affected by 'exclude_events'"
            )

        batch_export_model = model if isinstance(model, BatchExportModel) else None
        batch_export_schema = model if isinstance(model, dict) else None

        run = await self._run_workflow(
            destination_test=destination_test,
            batch_export_for_destination=batch_export_for_destination,
            team=ateam,
            data_interval_end=data_interval_end,
            interval=interval,
            batch_export_model=batch_export_model,
            batch_export_schema=batch_export_schema,
        )
        assert run.status == "Completed"

        events_to_export_created, persons_to_export_created = generate_test_data
        assert (
            run.records_completed == len(events_to_export_created)
            or run.records_completed == len(persons_to_export_created)
            or run.records_completed
            == len([event for event in events_to_export_created if event["properties"] is not None])
            or (isinstance(model, BatchExportModel) and model.name == "sessions" and run.records_completed <= 1)
        )

        # Assert data was written to destination
        await destination_test.assert_data_in_destination(
            team_id=ateam.pk,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            exclude_events=exclude_events,
            batch_export_model=model,
        )

    async def test_workflow_handles_unexpected_errors(
        self,
        destination_test: BaseDestinationTest,
        ateam,
        batch_export_for_destination,
    ):
        """Test that workflow handles unexpected errors gracefully and marks run as failed."""
        data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

        workflow_id = str(uuid.uuid4())
        inputs = destination_test.create_batch_export_inputs(
            team_id=ateam.pk,
            batch_export_id=str(batch_export_for_destination.id),
            data_interval_end=data_interval_end,
            interval="hour",
            **batch_export_for_destination.destination.config,
        )

        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[destination_test.workflow_class],
                activities=[
                    mocked_start_batch_export_run,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with pytest.raises(WorkflowFailureError):
                    await activity_environment.client.execute_workflow(
                        destination_test.workflow_class.run,
                        inputs,
                        id=workflow_id,
                        task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

        # Verify the run was marked as failed
        runs = await afetch_batch_export_runs(batch_export_id=batch_export_for_destination.id)
        assert len(runs) == 1

        run = runs[0]
        assert run.status == "FailedRetryable"
        assert run.records_completed is None

    async def test_workflow_handles_cancellation(
        self,
        destination_test: BaseDestinationTest,
        ateam,
        batch_export_for_destination,
    ):
        """Test that workflow handles cancellation gracefully."""
        data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

        @activity.defn(name="never_finish_activity")
        async def never_finish_activity(_) -> str:
            while True:
                activity.heartbeat()
                await asyncio.sleep(1)

        workflow_id = str(uuid.uuid4())
        inputs = destination_test.create_batch_export_inputs(
            team_id=ateam.pk,
            batch_export_id=str(batch_export_for_destination.id),
            data_interval_end=data_interval_end,
            interval="hour",
            **batch_export_for_destination.destination.config,
        )

        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[destination_test.workflow_class],
                activities=[
                    mocked_start_batch_export_run,
                    never_finish_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await activity_environment.client.start_workflow(
                    destination_test.workflow_class.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                await asyncio.sleep(5)
                await handle.cancel()

                with pytest.raises(WorkflowFailureError):
                    await handle.result()

        # Verify the run was marked as cancelled
        runs = await afetch_batch_export_runs(batch_export_id=batch_export_for_destination.id)
        assert len(runs) == 1

        run = runs[0]
        assert run.status == "Cancelled"
        assert run.latest_error == "Cancelled"

        await destination_test.assert_no_data_in_destination()

    async def test_workflow_without_events(
        self,
        destination_test: BaseDestinationTest,
        ateam,
        batch_export_for_destination,
        data_interval_start: dt.datetime,
        data_interval_end: dt.datetime,
    ):
        """Test workflow behavior when there are no events to export."""
        workflow_id = str(uuid.uuid4())
        inputs = destination_test.create_batch_export_inputs(
            team_id=ateam.pk,
            batch_export_id=str(batch_export_for_destination.id),
            data_interval_end=data_interval_end,
            interval="hour",
            **batch_export_for_destination.destination.config,
        )

        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[destination_test.workflow_class],
                activities=[
                    start_batch_export_run,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await activity_environment.client.execute_workflow(
                    destination_test.workflow_class.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=10),
                )

        # Verify the run completed with 0 records
        runs = await afetch_batch_export_runs(batch_export_id=batch_export_for_destination.id)
        assert len(runs) == 1

        run = runs[0]
        assert run.status == "Completed"
        assert run.records_completed == 0

        await destination_test.assert_no_data_in_destination()

"""Base test framework for batch export destinations.

This module provides a common test interface that can be implemented by each
destination to ensure consistent behavior and error handling across all destinations.
"""

import json
import uuid
import typing as t
import datetime as dt
import operator
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable

import pytest

from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog import constants
from posthog.batch_exports.models import BatchExport
from posthog.batch_exports.service import (
    BackfillDetails,
    BaseBatchExportInputs,
    BatchExportField,
    BatchExportModel,
    BatchExportSchema,
)
from posthog.models.integration import Integration
from posthog.models.team import Team
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import BATCH_EXPORT_WORKFLOW_TYPES as LOGGER_BATCH_EXPORT_WORKFLOW_TYPES
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export, afetch_batch_export_runs

from products.batch_exports.backend.temporal import ACTIVITIES, WORKFLOWS
from products.batch_exports.backend.temporal.batch_exports import finish_batch_export_run, start_batch_export_run
from products.batch_exports.backend.temporal.metrics import BATCH_EXPORT_ACTIVITY_TYPES, BATCH_EXPORT_WORKFLOW_TYPES
from products.batch_exports.backend.temporal.pipeline.internal_stage import insert_into_internal_stage_activity
from products.batch_exports.backend.temporal.record_batch_model import SessionsRecordBatchModel
from products.batch_exports.backend.temporal.spmc import Producer, RecordBatchQueue
from products.batch_exports.backend.tests.temporal.utils import (
    fail_on_application_error,
    get_record_batch_from_queue,
    remove_duplicates_from_records,
)


class RetryableTestException(Exception):
    """An exception to be raised during tests."""

    pass


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
    def workflow_class(self) -> type[PostHogWorkflow]:
        """Return the workflow class for this destination."""
        pass

    @property
    @abstractmethod
    def main_activity(self) -> Callable:
        """Return the main 'insert_into_*' activity for this destination."""
        pass

    @property
    @abstractmethod
    def batch_export_inputs_class(self) -> type[BaseBatchExportInputs]:
        """Return the inputs dataclass for the batch export workflow."""
        pass

    @property
    @abstractmethod
    def destination_default_fields(self) -> list[BatchExportField]:
        """Return the default fields for the destination."""
        pass

    def create_batch_export_inputs(
        self,
        team_id: int,
        data_interval_end: dt.datetime,
        interval: str,
        batch_export: BatchExport,
        batch_export_model: BatchExportModel | None = None,
        batch_export_schema: BatchExportSchema | None = None,
        backfill_details: BackfillDetails | None = None,
        **override_config,
    ):
        """Create workflow inputs for the destination."""
        return self.batch_export_inputs_class(
            team_id=team_id,
            batch_export_id=batch_export.id,
            data_interval_end=data_interval_end.isoformat(),
            interval=interval,
            batch_export_model=batch_export_model,
            batch_export_schema=batch_export_schema,
            backfill_details=backfill_details,
            integration_id=batch_export.destination.integration_id,
            **{**batch_export.destination.config, **override_config},
        )

    @abstractmethod
    def get_destination_config(self, team_id: int) -> dict:
        """Return the destination configuration."""
        pass

    async def create_integration(self, team_id: int) -> Integration | None:
        """Create a test integration (for those destinations that require an integration)"""
        return None

    @abstractmethod
    def get_json_columns(self, inputs: BaseBatchExportInputs) -> list[str]:
        """Return the JSON columns for the destination."""
        pass

    @abstractmethod
    def preprocess_records_before_comparison(self, records: list[dict[str, t.Any]]) -> list[dict[str, t.Any]]:
        """Preprocess the records before comparison (if required).

        For example, for some destinations we use a metadata field to track when the record was ingested into the
        destination. For this timestamp, we use now64(), which is not suitable for comparison, so we exclude it.
        """
        pass

    @abstractmethod
    async def get_inserted_records(
        self,
        team_id: int,
        json_columns: list[str],
        integration: Integration | None = None,
    ) -> list[dict[str, t.Any]]:
        pass

    @abstractmethod
    async def assert_no_data_in_destination(self, team_id: int, integration: "Integration | None" = None) -> None:
        """Assert that no data was written to the destination."""
        pass

    async def run_workflow(
        self,
        batch_export_id: uuid.UUID,
        inputs,
        expect_workflow_failure: bool = False,
    ):
        """Helper function to run the destination workflow"""

        workflow_id = str(uuid.uuid4())

        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[self.workflow_class],
                activities=[
                    start_batch_export_run,
                    insert_into_internal_stage_activity,
                    self.main_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                if expect_workflow_failure:
                    with pytest.raises(WorkflowFailureError):
                        await activity_environment.client.execute_workflow(
                            self.workflow_class.run,  # type: ignore[attr-defined]
                            inputs,
                            id=workflow_id,
                            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                            retry_policy=RetryPolicy(maximum_attempts=1),
                            execution_timeout=dt.timedelta(minutes=5),
                        )
                else:
                    with fail_on_application_error():
                        await activity_environment.client.execute_workflow(
                            self.workflow_class.run,  # type: ignore[attr-defined]
                            inputs,
                            id=workflow_id,
                            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                            retry_policy=RetryPolicy(maximum_attempts=1),
                            execution_timeout=dt.timedelta(minutes=5),
                        )

        runs = await afetch_batch_export_runs(batch_export_id=batch_export_id)
        assert len(runs)
        run = runs[0]
        return run


async def _get_records_from_clickhouse(
    team_id: int,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    exclude_events: list[str] | None,
    include_events: list[str] | None,
    batch_export_model: BatchExportModel | BatchExportSchema | None,
    backfill_details: BackfillDetails | None,
    expected_fields: list[str] | None,
    destination_default_fields: list[BatchExportField],
    json_columns: list[str] | None = None,
):
    """Get records from ClickHouse."""
    json_columns = json_columns or []
    if batch_export_model is not None:
        if isinstance(batch_export_model, BatchExportModel):
            model_name = batch_export_model.name
            fields = batch_export_model.schema["fields"] if batch_export_model.schema is not None else None
            filters = batch_export_model.filters
            extra_query_parameters = (
                batch_export_model.schema["values"] if batch_export_model.schema is not None else None
            )
        else:
            model_name = "custom"
            fields = batch_export_model["fields"]
            filters = None
            extra_query_parameters = batch_export_model["values"]
    else:
        model_name = "events"
        extra_query_parameters = None
        fields = None
        filters = None

    records = []
    queue = RecordBatchQueue()
    if model_name == "sessions":
        producer = Producer(model=SessionsRecordBatchModel(team_id))
    else:
        producer = Producer()

    producer_task = await producer.start(
        queue=queue,
        model_name=model_name,
        team_id=team_id,
        full_range=(data_interval_start, data_interval_end),
        done_ranges=[],
        fields=fields,
        filters=filters,
        destination_default_fields=destination_default_fields,
        exclude_events=exclude_events,
        include_events=include_events,
        is_backfill=backfill_details is not None,
        backfill_details=backfill_details,
        extra_query_parameters=extra_query_parameters,
    )
    while True:
        record_batch = await get_record_batch_from_queue(queue, producer_task)

        if record_batch is None:
            break

        select = record_batch.column_names
        if expected_fields:
            select = expected_fields

        # transform each record
        for original_record in record_batch.select(select).to_pylist():
            record = {}

            for k, v in original_record.items():
                if k == "_inserted_at":
                    # _inserted_at is not exported, only used for tracking progress.
                    continue

                if k in json_columns and isinstance(v, str):
                    record[k] = json.loads(v)
                elif k == "elements":
                    # Happens transparently when uploading elements as a variant field.
                    record[k] = json.dumps(v)
                else:
                    record[k] = v

            records.append(record)

    return records


async def assert_clickhouse_records_in_destination(
    destination_test: BaseDestinationTest,
    team_id: int,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    inputs: BaseBatchExportInputs,
    batch_export_model: BatchExportModel | BatchExportSchema | None = None,
    backfill_details: BackfillDetails | None = None,
    expected_fields: list[str] | None = None,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    expect_duplicates: bool = False,
    primary_key: list[str] | None = None,
    fields_to_exclude: list[str] | None = None,
    integration: Integration | None = None,
):
    """Assert that the expected data was written to the destination."""
    json_columns = destination_test.get_json_columns(inputs)
    records_from_clickhouse = await _get_records_from_clickhouse(
        team_id=team_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        include_events=include_events,
        batch_export_model=batch_export_model,
        backfill_details=backfill_details,
        expected_fields=expected_fields,
        destination_default_fields=destination_test.destination_default_fields,
        json_columns=json_columns,
    )
    records_from_destination = await destination_test.get_inserted_records(
        team_id=team_id,
        json_columns=json_columns,
        integration=integration,
    )

    # Determine sort key based on model
    sort_key = "uuid"
    if isinstance(batch_export_model, BatchExportModel):
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

    if expect_duplicates:
        records_from_destination = remove_duplicates_from_records(records_from_destination, primary_key)

    assert records_from_destination, "No records were inserted into the destination"

    fields_to_exclude = fields_to_exclude or []
    records_from_destination = [
        {k: v for k, v in record.items() if k not in fields_to_exclude} for record in records_from_destination
    ]
    records_from_clickhouse = [
        {k: v for k, v in record.items() if k not in fields_to_exclude} for record in records_from_clickhouse
    ]
    records_from_destination = destination_test.preprocess_records_before_comparison(records_from_destination)
    records_from_clickhouse = destination_test.preprocess_records_before_comparison(records_from_clickhouse)

    inserted_column_names = list(records_from_destination[0].keys())
    expected_column_names = list(records_from_clickhouse[0].keys())
    inserted_column_names.sort()
    expected_column_names.sort()
    assert len(inserted_column_names) > 0
    assert inserted_column_names == expected_column_names

    # Ordering is not guaranteed, so we sort before comparing.
    records_from_destination.sort(key=operator.itemgetter(sort_key))
    records_from_clickhouse.sort(key=operator.itemgetter(sort_key))

    assert len(records_from_destination) == len(records_from_clickhouse)
    assert records_from_destination[0] == records_from_clickhouse[0]
    assert records_from_destination == records_from_clickhouse


class CommonWorkflowTests:
    """Common test patterns for all batch export workflows.

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
    async def batch_export_for_destination(
        self, ateam, temporal_client, interval, integration, destination_test, exclude_events
    ) -> AsyncGenerator[BatchExport, None]:
        """Manage BatchExport model (and associated Temporal Schedule) for tests"""
        destination_config = {**destination_test.get_destination_config(ateam.pk), "exclude_events": exclude_events}
        destination_data = {
            "type": destination_test.destination_type,
            "config": destination_config,
            "integration_id": integration.pk if integration else None,
        }

        batch_export_data = {
            "name": "my-production-destination-export",
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
    async def invalid_batch_export_for_destination(
        self, ateam, temporal_client, interval, invalid_integration, destination_test, exclude_events
    ) -> AsyncGenerator[tuple[BatchExport, str], None]:
        integration, expected_error_message = invalid_integration
        destination_config = {**destination_test.get_destination_config(ateam.pk), "exclude_events": exclude_events}
        destination_data = {
            "type": destination_test.destination_type,
            "config": destination_config,
            "integration_id": integration.pk if integration else None,
        }

        batch_export_data = {
            "name": "my-production-destination-export",
            "destination": destination_data,
            "interval": interval,
        }

        batch_export = await acreate_batch_export(
            team_id=ateam.pk,
            name=batch_export_data["name"],
            destination_data=batch_export_data["destination"],
            interval=batch_export_data["interval"],
        )

        yield batch_export, expected_error_message

        await adelete_batch_export(batch_export, temporal_client)

    @pytest.fixture
    def destination_test(self, ateam: Team):
        raise NotImplementedError("destination_test fixture must be implemented by destination-specific tests")

    @pytest.fixture
    async def integration(self, ateam):
        """Create a test integration (for those destinations that require an integration)"""
        raise NotImplementedError("integration fixture must be implemented by destination-specific tests")

    @pytest.fixture
    def simulate_unexpected_error(self):
        raise NotImplementedError("simulate_unexpected_error fixture must be implemented by destination-specific tests")

    def test_workflow_and_activities_are_registered(
        self,
        destination_test: BaseDestinationTest,
    ):
        """Test that the workflow and activities are registered in the right places"""
        assert destination_test.workflow_class in WORKFLOWS
        assert destination_test.main_activity in ACTIVITIES
        # also check the workflow and activity names are set up for metric handling
        assert destination_test.workflow_class.get_name() in BATCH_EXPORT_WORKFLOW_TYPES
        assert destination_test.main_activity.__name__ in BATCH_EXPORT_ACTIVITY_TYPES
        # also check the workflow name is in this list we use for logging
        # TODO: we should probably consolidate these lists somewhere, except for now they're not exactly the same (one
        # includes http-export, while the other doesn't)
        assert destination_test.workflow_class.get_name() in LOGGER_BATCH_EXPORT_WORKFLOW_TYPES

    @pytest.mark.parametrize("interval", ["hour"], indirect=True)
    @pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
    @pytest.mark.parametrize("model", TEST_MODELS)
    async def test_workflow_completes_successfully(
        self,
        destination_test: BaseDestinationTest,
        interval: str,
        exclude_events: list[str] | None,
        model: BatchExportModel | BatchExportSchema | None,
        generate_test_data,
        data_interval_start: dt.datetime,
        data_interval_end: dt.datetime,
        ateam,
        batch_export_for_destination,  # This fixture needs to be provided by destination-specific tests
        integration,
        setup_destination,
    ):
        """Test that the workflow completes successfully end-to-end.

        We test this for all models using a single interval.
        """
        if isinstance(model, BatchExportModel) and model.name != "events" and exclude_events is not None:
            pytest.skip(
                f"Unnecessary test case as batch export model '{model.name}' is not affected by 'exclude_events'"
            )

        batch_export_schema: BatchExportSchema | None = None
        batch_export_model: BatchExportModel | None = None
        if isinstance(model, BatchExportModel):
            batch_export_model = model
        elif model is not None:
            batch_export_schema = model

        inputs = destination_test.create_batch_export_inputs(
            team_id=ateam.pk,
            data_interval_end=data_interval_end,
            interval=interval,
            batch_export=batch_export_for_destination,
            batch_export_schema=batch_export_schema,
            batch_export_model=batch_export_model,
        )

        run = await destination_test.run_workflow(
            batch_export_id=batch_export_for_destination.id,
            inputs=inputs,
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

        await assert_clickhouse_records_in_destination(
            destination_test=destination_test,
            team_id=ateam.pk,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            batch_export_model=batch_export_model or batch_export_schema,
            exclude_events=exclude_events,
            inputs=inputs,
            integration=integration,
        )

    async def test_workflow_without_events(
        self,
        destination_test: BaseDestinationTest,
        ateam,
        batch_export_for_destination,
        data_interval_start: dt.datetime,
        data_interval_end: dt.datetime,
        integration,
        setup_destination,
    ):
        """Test workflow behavior when there are no events to export."""
        inputs = destination_test.create_batch_export_inputs(
            team_id=ateam.pk,
            data_interval_end=data_interval_end,
            interval="hour",
            batch_export_model=BatchExportModel(name="events", schema=None),
            batch_export=batch_export_for_destination,
        )

        run = await destination_test.run_workflow(
            batch_export_id=batch_export_for_destination.id,
            inputs=inputs,
        )
        assert run.status == "Completed"
        assert run.records_completed == 0
        assert run.bytes_exported == 0

        await destination_test.assert_no_data_in_destination(
            team_id=ateam.pk,
            integration=integration,
        )

    async def test_workflow_handles_unexpected_errors(
        self,
        destination_test: BaseDestinationTest,
        ateam,
        data_interval_end: dt.datetime,
        batch_export_for_destination,
        simulate_unexpected_error,
        integration,
        setup_destination,
    ):
        """Test that workflow handles unexpected errors gracefully.

        This means we do the right updates to the BatchExportRun model.

        We expect the workflow to fail as in our tests we don't retry activities that fail.
        """

        inputs = destination_test.create_batch_export_inputs(
            team_id=ateam.pk,
            data_interval_end=data_interval_end,
            interval="hour",
            batch_export_model=BatchExportModel(name="events", schema=None),
            batch_export=batch_export_for_destination,
        )

        run = await destination_test.run_workflow(
            batch_export_id=batch_export_for_destination.id,
            inputs=inputs,
            # We expect the workflow to fail as in our tests we don't retry activities that fail.
            expect_workflow_failure=True,
        )
        assert run.status == "FailedRetryable"
        assert run.latest_error == "RetryableTestException: A useful error message"
        assert run.records_completed is None
        assert run.bytes_exported is None

    async def test_workflow_handles_non_retryable_errors(
        self,
        destination_test: BaseDestinationTest,
        ateam,
        generate_test_data,
        data_interval_end: dt.datetime,
        invalid_batch_export_for_destination,
        setup_destination,
    ):
        """Test that workflow handles non-retryable errors gracefully.

        This means we do the right updates to the BatchExportRun model and ensure the workflow succeeds (since we treat
        this as a user error).

        To simulate a user error, we use an integration with invalid connection parameters.
        """
        batch_export_for_destination, expected_error_message = invalid_batch_export_for_destination

        inputs = destination_test.create_batch_export_inputs(
            team_id=ateam.pk,
            data_interval_end=data_interval_end,
            interval="hour",
            batch_export_model=BatchExportModel(name="events", schema=None),
            batch_export=batch_export_for_destination,
        )

        run = await destination_test.run_workflow(
            batch_export_id=batch_export_for_destination.id,
            inputs=inputs,
        )
        assert run.status == "Failed"
        assert run.latest_error == expected_error_message
        assert run.records_completed is None
        assert run.bytes_exported is None

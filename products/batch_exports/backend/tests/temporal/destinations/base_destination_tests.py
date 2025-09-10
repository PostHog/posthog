"""Base test framework for batch export destinations.

This module provides a common test interface that can be implemented by each
destination to ensure consistent behavior and error handling across all destinations.
"""

import json
import uuid
import typing as t
import asyncio
import datetime as dt
import operator
from abc import ABC, abstractmethod
from collections.abc import Callable

import pytest

from temporalio import activity
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
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export, afetch_batch_export_runs

from products.batch_exports.backend.temporal.batch_exports import finish_batch_export_run, start_batch_export_run
from products.batch_exports.backend.temporal.pipeline.internal_stage import insert_into_internal_stage_activity
from products.batch_exports.backend.temporal.record_batch_model import SessionsRecordBatchModel
from products.batch_exports.backend.temporal.spmc import Producer, RecordBatchQueue
from products.batch_exports.backend.tests.temporal.utils import (
    fail_on_application_error,
    get_record_batch_from_queue,
    mocked_start_batch_export_run,
    remove_duplicates_from_records,
)


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

    @property
    @abstractmethod
    def destination_default_fields(self) -> list[BatchExportField]:
        """Return the default fields for the destination."""
        pass

    def create_batch_export_inputs(
        self,
        team_id: int,
        batch_export_id: str,
        data_interval_end: dt.datetime,
        interval: str,
        batch_export_model: BatchExportModel | None = None,
        batch_export_schema: BatchExportSchema | None = None,
        backfill_details: BackfillDetails | None = None,
        **config,
    ):
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
    def get_json_columns(self, inputs: BaseBatchExportInputs) -> list[str]:
        """Return the JSON columns for the destination."""
        pass

    @abstractmethod
    async def get_inserted_records(
        self,
        team_id: int,
        json_columns: list[str],
    ) -> list[dict[str, t.Any]]:
        pass

    @abstractmethod
    async def assert_no_data_in_destination(self, **kwargs) -> None:
        """Assert that no data was written to the destination."""
        pass


async def _run_workflow(
    destination_test: BaseDestinationTest,
    batch_export_for_destination: BatchExport,
    inputs,
):
    """Helper function to run SnowflakeBatchExportWorkflow and assert records in Snowflake"""

    workflow_id = str(uuid.uuid4())
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
            with fail_on_application_error():
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
                elif isinstance(v, dt.datetime):
                    # By default, Snowflake's `TIMESTAMP` doesn't include a timezone component.
                    record[k] = v.replace(tzinfo=None)
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

    assert records_from_destination, "No records were inserted into Snowflake"
    inserted_column_names = list(records_from_destination[0].keys())
    expected_column_names = list(records_from_clickhouse[0].keys())
    inserted_column_names.sort()
    expected_column_names.sort()

    # Ordering is not guaranteed, so we sort before comparing.
    records_from_destination.sort(key=operator.itemgetter(sort_key))
    records_from_clickhouse.sort(key=operator.itemgetter(sort_key))

    assert inserted_column_names == expected_column_names
    assert len(records_from_destination) == len(records_from_clickhouse)
    assert records_from_destination[0] == records_from_clickhouse[0]
    assert records_from_destination == records_from_clickhouse
    assert len(inserted_column_names) > 0


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
            batch_export_id=str(batch_export_for_destination.id),
            data_interval_end=data_interval_end,
            interval=interval,
            batch_export_schema=batch_export_schema,
            batch_export_model=batch_export_model,
            **batch_export_for_destination.destination.config,
        )

        run = await _run_workflow(
            destination_test=destination_test,
            batch_export_for_destination=batch_export_for_destination,
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

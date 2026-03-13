"""
Test the Snowflake Export Workflow.

Note: This module uses a real Snowflake connection.
"""

import asyncio
import datetime as dt
from uuid import uuid4

import pytest

from django.conf import settings
from django.test import override_settings

from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.batch_exports.service import BackfillDetails, BatchExportModel, BatchExportSchema
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.temporal.tests.utils.models import afetch_batch_export_runs

from products.batch_exports.backend.temporal.batch_exports import finish_batch_export_run, start_batch_export_run
from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    SnowflakeBatchExportInputs,
    SnowflakeBatchExportWorkflow,
    insert_into_snowflake_activity_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import insert_into_internal_stage_activity
from products.batch_exports.backend.tests.temporal.destinations.snowflake.utils import (
    SKIP_IF_MISSING_REQUIRED_ENV_VARS,
    TEST_MODELS,
    TEST_TIME,
    assert_clickhouse_records_in_snowflake,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
    SKIP_IF_MISSING_REQUIRED_ENV_VARS,
]


async def _run_workflow(
    clickhouse_client,
    snowflake_cursor,
    snowflake_batch_export,
    team,
    data_interval_start,
    data_interval_end,
    interval: str,
    batch_export_model: BatchExportModel | None = None,
    batch_export_schema: BatchExportSchema | None = None,
    exclude_events=None,
    backfill_details=None,
    settings_overrides=None,
    execution_timeout=dt.timedelta(minutes=2),
    expected_status: str = "Completed",
    sort_key: str = "event",
    expect_data_interval_start_none: bool = False,
):
    """Helper function to run SnowflakeBatchExportWorkflow and assert records in Snowflake"""
    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=team.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        backfill_details=backfill_details,
        **snowflake_batch_export.destination.config,
    )

    settings_overrides = settings_overrides or {}

    async with (
        await WorkflowEnvironment.start_time_skipping() as activity_environment,
        Worker(
            activity_environment.client,
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_internal_stage_activity,
                insert_into_snowflake_activity_from_stage,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        with override_settings(**settings_overrides):
            await activity_environment.client.execute_workflow(
                SnowflakeBatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=execution_timeout,
            )

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == expected_status

    if expect_data_interval_start_none:
        assert run.data_interval_start is None

    # Determine sort key based on model
    if batch_export_model is not None:
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

    await assert_clickhouse_records_in_snowflake(
        snowflake_cursor=snowflake_cursor,
        clickhouse_client=clickhouse_client,
        table_name=snowflake_batch_export.destination.config["table_name"],
        team_id=team.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        batch_export_model=batch_export_model or batch_export_schema,
        sort_key=sort_key,
    )

    return run


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_snowflake_export_workflow(
    clickhouse_client,
    snowflake_cursor,
    interval,
    snowflake_batch_export,
    ateam,
    exclude_events,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
):
    """Test Snowflake Export Workflow end-to-end.

    The workflow should update the batch export run status to completed and produce the expected
    records to the provided Snowflake instance.
    """
    if isinstance(model, BatchExportModel) and model.name != "events" and exclude_events is not None:
        pytest.skip("Unnecessary test case as batch export model is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    await _run_workflow(
        clickhouse_client=clickhouse_client,
        snowflake_cursor=snowflake_cursor,
        snowflake_batch_export=snowflake_batch_export,
        team=ateam,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        interval=interval,
        batch_export_model=batch_export_model,
        batch_export_schema=batch_export_schema,
        exclude_events=exclude_events,
    )


@pytest.mark.parametrize("exclude_events", [None], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="events", schema=None)])
async def test_snowflake_export_workflow_with_many_files(
    clickhouse_client,
    snowflake_cursor,
    interval,
    snowflake_batch_export,
    ateam,
    exclude_events,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
):
    """Test Snowflake Export Workflow end-to-end with multiple file uploads.

    This test overrides the chunk size and sets it to 1 byte to trigger multiple file uploads.
    We want to assert that all files are properly copied into the table. Of course, 1 byte limit
    means we are uploading one file at a time, which is very innefficient. For this reason, this test
    can take longer, so we keep the event count low and bump the Workflow timeout.
    """
    if isinstance(model, BatchExportModel) and model.name != "events" and exclude_events is not None:
        pytest.skip("Unnecessary test case as batch export model is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    await _run_workflow(
        clickhouse_client=clickhouse_client,
        snowflake_cursor=snowflake_cursor,
        snowflake_batch_export=snowflake_batch_export,
        team=ateam,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        interval=interval,
        batch_export_model=batch_export_model,
        batch_export_schema=batch_export_schema,
        exclude_events=exclude_events,
        settings_overrides={"BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES": 1},
    )


@pytest.mark.parametrize(
    "data_interval_start",
    # This is set to 24 hours before the `data_interval_end` to ensure that the data created is outside the batch
    # interval.
    [TEST_TIME - dt.timedelta(hours=24)],
    indirect=True,
)
@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="persons", schema=None)])
async def test_snowflake_export_workflow_backfill_earliest_persons(
    ateam,
    clickhouse_client,
    data_interval_start,
    data_interval_end,
    generate_test_data,
    interval,
    model,
    snowflake_batch_export,
    snowflake_cursor,
):
    """Test a `SnowflakeBatchExportWorkflow` backfilling the persons model.

    We expect persons outside the batch interval to also be backfilled (i.e. persons that were updated
    more than an hour ago) when setting `is_earliest_backfill=True`.
    """
    _, persons = generate_test_data

    # Ensure some data outside batch interval has been created
    assert any(
        data_interval_end - person["_timestamp"].replace(tzinfo=dt.UTC) > dt.timedelta(hours=12) for person in persons
    )

    backfill_details = BackfillDetails(
        backfill_id=None,
        is_earliest_backfill=True,
        start_at=None,
        end_at=data_interval_end.isoformat(),
    )

    await _run_workflow(
        clickhouse_client=clickhouse_client,
        snowflake_cursor=snowflake_cursor,
        snowflake_batch_export=snowflake_batch_export,
        team=ateam,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        interval=interval,
        batch_export_model=model,
        backfill_details=backfill_details,
        settings_overrides={"BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES": 1},
        execution_timeout=dt.timedelta(minutes=10),
        expect_data_interval_start_none=True,
    )


async def test_snowflake_export_workflow_handles_cancellation(
    clickhouse_client,
    ateam,
    snowflake_batch_export,
    interval,
    snowflake_cursor,
):
    """Test that Snowflake Export Workflow can gracefully handle cancellations when inserting Snowflake data."""
    data_interval_end = dt.datetime.now(dt.UTC)
    data_interval_start = data_interval_end - snowflake_batch_export.interval_time_delta

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=100,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )

    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **snowflake_batch_export.destination.config,
    )

    async with (
        await WorkflowEnvironment.start_time_skipping() as activity_environment,
        Worker(
            activity_environment.client,
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_internal_stage_activity,
                insert_into_snowflake_activity_from_stage,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        # We set the chunk size low on purpose to slow things down and give us time to cancel.
        with override_settings(BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES=1):
            handle = await activity_environment.client.start_workflow(
                SnowflakeBatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

        # We need to wait a bit for the activity to start running.
        await asyncio.sleep(5)
        await handle.cancel()

        with pytest.raises(WorkflowFailureError):
            await handle.result()

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Cancelled"
    assert run.latest_error == "Cancelled"

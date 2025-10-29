"""
Test the Snowflake Export Workflow.

Note: This module uses a mocked Snowflake connection.
"""

import asyncio
import datetime as dt
from uuid import uuid4

import pytest
import unittest.mock

from django.test import override_settings

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog import constants
from posthog.batch_exports.models import BatchExport, BatchExportRun
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.temporal.tests.utils.models import afetch_batch_export_runs

from products.batch_exports.backend.temporal.batch_exports import finish_batch_export_run, start_batch_export_run
from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    SnowflakeBatchExportInputs,
    SnowflakeBatchExportWorkflow,
    SnowflakeInsertInputs,
    insert_into_snowflake_activity_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import insert_into_internal_stage_activity
from products.batch_exports.backend.tests.temporal.destinations.snowflake.utils import (
    TEST_TIME,
    FakeSnowflakeConnection,
)
from products.batch_exports.backend.tests.temporal.utils.workflow import mocked_start_batch_export_run

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
]


async def _run_workflow(
    team_id: int,
    batch_export_id: int,
    interval: str,
    snowflake_batch_export: BatchExport,
    data_interval_end: dt.datetime = TEST_TIME,
) -> BatchExportRun:
    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=team_id,
        batch_export_id=str(batch_export_id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **snowflake_batch_export.destination.config,
    )

    async with (
        await WorkflowEnvironment.start_time_skipping() as activity_environment,
        Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
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
        await activity_environment.client.execute_workflow(
            SnowflakeBatchExportWorkflow.run,
            inputs,
            id=workflow_id,
            execution_timeout=dt.timedelta(seconds=10),
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    return run


@pytest.fixture
def mock_snowflake_connection():
    with (
        unittest.mock.patch(
            "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.snowflake.connector.connect",
        ) as mock,
        unittest.mock.patch(
            "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.SnowflakeClient.DEFAULT_POLL_INTERVAL",
            0.01,
        ),
        override_settings(BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES=1),
    ):
        fake_conn = FakeSnowflakeConnection()
        mock.return_value = fake_conn
        yield fake_conn


@pytest.mark.parametrize("interval", ["hour"], indirect=True)
async def test_snowflake_export_workflow_exports_events(
    ateam,
    clickhouse_client,
    database,
    schema,
    snowflake_batch_export,
    interval,
    table_name,
    mock_snowflake_connection,
):
    """Test that the whole workflow not just the activity works.

    It should update the batch export run status to completed, as well as updating the record
    count.
    """
    data_interval_end = dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    data_interval_end_str = data_interval_end.strftime("%Y-%m-%d_%H-%M-%S")
    data_interval_start = data_interval_end - snowflake_batch_export.interval_time_delta

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )
    run = await _run_workflow(
        team_id=ateam.pk,
        batch_export_id=snowflake_batch_export.id,
        data_interval_end=data_interval_end,
        interval=interval,
        snowflake_batch_export=snowflake_batch_export,
    )
    assert run.status == "Completed"
    assert run.records_completed == 10

    fake_conn = mock_snowflake_connection

    execute_calls = []
    for cursor in fake_conn._cursors:
        for call in cursor._execute_calls:
            execute_calls.append(call["query"].strip())

    execute_async_calls = []
    for cursor in fake_conn._cursors:
        for call in cursor._execute_async_calls:
            execute_async_calls.append(call["query"].strip())

    assert execute_async_calls[0:3] == [
        f'USE DATABASE "{database}"',
        f'USE SCHEMA "{schema}"',
        "SET ABORT_DETACHED_QUERY = FALSE",
    ]

    assert all(query.startswith("PUT") for query in execute_calls[0:9])

    assert execute_async_calls[3].startswith(f'CREATE TABLE IF NOT EXISTS "{table_name}"')
    assert execute_async_calls[4].startswith(f"""REMOVE '@%"{table_name}"/{data_interval_end_str}'""")
    assert execute_async_calls[5].startswith(f'COPY INTO "{table_name}"')


@pytest.mark.parametrize("interval", ["hour"], indirect=True)
async def test_snowflake_export_workflow_without_events(ateam, snowflake_batch_export, interval):
    data_interval_end = dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    run = await _run_workflow(
        team_id=ateam.pk,
        batch_export_id=snowflake_batch_export.id,
        data_interval_end=data_interval_end,
        interval=interval,
        snowflake_batch_export=snowflake_batch_export,
    )
    assert run.status == "Completed"
    assert run.records_completed == 0


async def test_snowflake_export_workflow_raises_error_on_put_fail(
    clickhouse_client, ateam, snowflake_batch_export, interval
):
    data_interval_end = TEST_TIME
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

    class FakeSnowflakeConnectionFailOnPut(FakeSnowflakeConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, failure_mode="put", **kwargs)

    with (
        unittest.mock.patch(
            "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.snowflake.connector.connect",
            side_effect=FakeSnowflakeConnectionFailOnPut,
        ),
        unittest.mock.patch(
            "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.SnowflakeClient.DEFAULT_POLL_INTERVAL",
            0.01,
        ),
    ):
        with pytest.raises(WorkflowFailureError) as exc_info:
            run = await _run_workflow(
                team_id=ateam.pk,
                batch_export_id=snowflake_batch_export.id,
                data_interval_end=data_interval_end,
                interval=interval,
                snowflake_batch_export=snowflake_batch_export,
            )
            assert run.status == "FailedRetryable"
            assert run.latest_error == "SnowflakeFileNotUploadedError"

        err = exc_info.value
        assert hasattr(err, "__cause__"), "Workflow failure missing cause"
        assert isinstance(err.__cause__, ActivityError)
        assert isinstance(err.__cause__.__cause__, ApplicationError)
        assert err.__cause__.__cause__.type == "SnowflakeFileNotUploadedError"


async def test_snowflake_export_workflow_raises_error_on_copy_fail(
    clickhouse_client, ateam, snowflake_batch_export, interval
):
    data_interval_end = dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
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

    class FakeSnowflakeConnectionFailOnCopy(FakeSnowflakeConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, failure_mode="copy", **kwargs)

    with (
        unittest.mock.patch(
            "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.snowflake.connector.connect",
            side_effect=FakeSnowflakeConnectionFailOnCopy,
        ),
        unittest.mock.patch(
            "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.SnowflakeClient.DEFAULT_POLL_INTERVAL",
            0.01,
        ),
    ):
        with pytest.raises(WorkflowFailureError) as exc_info:
            run = await _run_workflow(
                team_id=ateam.pk,
                batch_export_id=snowflake_batch_export.id,
                data_interval_end=data_interval_end,
                interval=interval,
                snowflake_batch_export=snowflake_batch_export,
            )
            assert run.status == "FailedRetryable"
            assert run.latest_error == "SnowflakeFileNotLoadedError"

        err = exc_info.value
        assert hasattr(err, "__cause__"), "Workflow failure missing cause"
        assert isinstance(err.__cause__, ActivityError)
        assert isinstance(err.__cause__.__cause__, ApplicationError)
        assert err.__cause__.__cause__.type == "SnowflakeFileNotLoadedError"


async def test_snowflake_export_workflow_handles_unexpected_insert_activity_errors(
    ateam, snowflake_batch_export, interval
):
    """Test that Snowflake Export Workflow can gracefully handle unexpected errors when inserting Snowflake data.

    This means we do the right updates to the BatchExportRun model and ensure the workflow fails (since we
    treat this as an unexpected internal error).

    To simulate an unexpected error, we mock the `Producer.start` method.
    """

    with unittest.mock.patch(
        "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.Producer.start",
        side_effect=ValueError("A useful error message"),
    ):
        with pytest.raises(WorkflowFailureError):
            run = await _run_workflow(
                team_id=ateam.pk,
                batch_export_id=snowflake_batch_export.id,
                interval=interval,
                snowflake_batch_export=snowflake_batch_export,
            )
            assert run.status == "FailedRetryable"
            assert run.latest_error == "ValueError: A useful error message"
            assert run.records_completed is None


async def test_snowflake_export_workflow_handles_insert_activity_non_retryable_errors(
    ateam, snowflake_batch_export, interval
):
    """Test that Snowflake Export Workflow can gracefully handle non-retryable errors when inserting Snowflake data.

    In this case, we expect the workflow to succeed, but the batch export run to be marked as failed.

    To simulate a user error, we mock the `Producer.start` method.
    """

    class ForbiddenError(Exception):
        pass

    with unittest.mock.patch(
        "products.batch_exports.backend.temporal.destinations.snowflake_batch_export.Producer.start",
        side_effect=ForbiddenError("A useful error message"),
    ):
        run = await _run_workflow(
            team_id=ateam.pk,
            batch_export_id=snowflake_batch_export.id,
            interval=interval,
            snowflake_batch_export=snowflake_batch_export,
        )
    assert run.status == "Failed"
    assert run.latest_error == "ForbiddenError: A useful error message"
    assert run.records_completed is None


async def test_snowflake_export_workflow_handles_cancellation_mocked(ateam, snowflake_batch_export):
    """Test that Snowflake Export Workflow can gracefully handle cancellations when inserting Snowflake data.

    We mock the insert_into_snowflake_activity for this test.
    """
    data_interval_end = dt.datetime.now(dt.UTC)
    workflow_id = str(uuid4())
    inputs = SnowflakeBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(snowflake_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        **snowflake_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_snowflake_activity_from_stage")
    async def never_finish_activity_from_stage(_: SnowflakeInsertInputs) -> str:
        while True:
            activity.heartbeat()
            await asyncio.sleep(1)

    async with (
        await WorkflowEnvironment.start_time_skipping() as activity_environment,
        Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[SnowflakeBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_internal_stage_activity,
                never_finish_activity_from_stage,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        handle = await activity_environment.client.start_workflow(
            SnowflakeBatchExportWorkflow.run,
            inputs,
            id=workflow_id,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        await asyncio.sleep(5)
        await handle.cancel()

        with pytest.raises(WorkflowFailureError):
            await handle.result()

    runs = await afetch_batch_export_runs(batch_export_id=snowflake_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Cancelled"
    assert run.latest_error == "Cancelled"

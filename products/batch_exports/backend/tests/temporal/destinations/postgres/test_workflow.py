"""Test module covering the workflow used for batch exporting to Postgres.

The tests are parametrized with `use_internal_stage` to cover both usage of
`insert_into_postgres_activity` or `insert_into_postgres_activity_from_stage` as the
main activities of the workflow.

NOTE: Once all batch exports have been moved to use the internal stage, the
`use_internal_stage` parameter can be dropped with only the `True` case remaining.
"""

import uuid
import asyncio
import datetime as dt

import pytest
import unittest.mock

from django.test import override_settings

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog import constants
from posthog.batch_exports.service import BackfillDetails, BatchExportModel, BatchExportSchema
from posthog.temporal.tests.utils.models import afetch_batch_export_runs

from products.batch_exports.backend.temporal.batch_exports import finish_batch_export_run, start_batch_export_run
from products.batch_exports.backend.temporal.destinations.postgres_batch_export import (
    PostgresBatchExportInputs,
    PostgresBatchExportWorkflow,
    PostgresInsertInputs,
    insert_into_postgres_activity,
    insert_into_postgres_activity_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import insert_into_internal_stage_activity
from products.batch_exports.backend.tests.temporal.destinations.postgres.utils import (
    TEST_MODELS,
    assert_clickhouse_records_in_postgres,
)
from products.batch_exports.backend.tests.temporal.utils.workflow import mocked_start_batch_export_run

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
    # While we migrate to the new workflow, we need to test both new and old activities
    pytest.mark.parametrize("use_internal_stage", [False, True]),
]


@pytest.mark.parametrize("interval", ["hour", "day"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_postgres_export_workflow(
    clickhouse_client,
    postgres_config,
    postgres_connection,
    postgres_batch_export,
    interval,
    exclude_events,
    ateam,
    table_name,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    use_internal_stage,
):
    """Test Postgres Export Workflow end-to-end by using a local PG database.

    The workflow should update the batch export run status to completed and produce the expected
    records to the local development PostgreSQL database.
    """
    if (
        isinstance(model, BatchExportModel)
        and (model.name == "persons" or model.name == "sessions")
        and exclude_events is not None
    ):
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    workflow_id = str(uuid.uuid4())
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **postgres_batch_export.destination.config,
    )

    sort_key = "event"
    if batch_export_model is not None:
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_POSTGRES_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[PostgresBatchExportWorkflow],
                activities=[
                    start_batch_export_run,
                    insert_into_postgres_activity,
                    insert_into_postgres_activity_from_stage,
                    insert_into_internal_stage_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with override_settings(BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
                    await activity_environment.client.execute_workflow(
                        PostgresBatchExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                        execution_timeout=dt.timedelta(seconds=10),
                    )

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    events_to_export_created, persons_to_export_created = generate_test_data

    run = runs[0]
    assert run.status == "Completed"
    assert (
        run.records_completed == len(events_to_export_created)
        or run.records_completed == len(persons_to_export_created)
        or run.records_completed
        == len([event for event in events_to_export_created if event["properties"] is not None])
        or (isinstance(model, BatchExportModel) and model.name == "sessions" and run.records_completed == 1)
    )

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        sort_key=sort_key,
    )


@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_postgres_export_workflow_without_events(
    clickhouse_client,
    postgres_config,
    postgres_connection,
    postgres_batch_export,
    interval,
    exclude_events,
    ateam,
    table_name,
    model: BatchExportModel | BatchExportSchema | None,
    data_interval_start,
    data_interval_end,
    use_internal_stage,
):
    """Test Postgres Export Workflow end-to-end without any events to export.

    The workflow should update the batch export run status to completed and set 0 as `records_completed`.
    """
    if (
        isinstance(model, BatchExportModel)
        and (model.name == "persons" or model.name == "sessions")
        and exclude_events is not None
    ):
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    workflow_id = str(uuid.uuid4())
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **postgres_batch_export.destination.config,
    )

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_POSTGRES_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[PostgresBatchExportWorkflow],
                activities=[
                    start_batch_export_run,
                    insert_into_postgres_activity,
                    insert_into_postgres_activity_from_stage,
                    insert_into_internal_stage_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with override_settings(BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
                    await activity_environment.client.execute_workflow(
                        PostgresBatchExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                        execution_timeout=dt.timedelta(seconds=10),
                    )

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"
    assert run.records_completed == 0


@pytest.mark.parametrize(
    "data_interval_start",
    # This is set to 24 hours before the `data_interval_end` to ensure that the data created is outside the batch
    # interval.
    [dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(hours=24)],
    indirect=True,
)
@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="persons", schema=None)])
async def test_postgres_export_workflow_backfill_earliest_persons(
    ateam,
    clickhouse_client,
    postgres_config,
    postgres_connection,
    postgres_batch_export,
    interval,
    exclude_events,
    data_interval_start,
    data_interval_end,
    model,
    generate_test_data,
    table_name,
    use_internal_stage,
):
    """Test a `PostgresBatchExportWorkflow` backfilling the persons model.

    We expect persons outside the batch interval to also be backfilled (i.e. persons that were updated
    more than an hour ago) when setting `is_earliest_backfill=True`.
    """
    backfill_details = BackfillDetails(
        backfill_id=None,
        is_earliest_backfill=True,
        start_at=None,
        end_at=data_interval_end.isoformat(),
    )
    workflow_id = str(uuid.uuid4())
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_model=model,
        backfill_details=backfill_details,
        **postgres_batch_export.destination.config,
    )
    _, persons = generate_test_data

    # Ensure some data outside batch interval has been created
    assert any(
        data_interval_end - person["_timestamp"].replace(tzinfo=dt.UTC) > dt.timedelta(hours=12) for person in persons
    )

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_POSTGRES_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[PostgresBatchExportWorkflow],
                activities=[
                    start_batch_export_run,
                    insert_into_postgres_activity,
                    insert_into_postgres_activity_from_stage,
                    insert_into_internal_stage_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await activity_environment.client.execute_workflow(
                    PostgresBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(minutes=10),
                )

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"
    assert run.data_interval_start is None

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=table_name,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        sort_key="person_id",
        backfill_details=backfill_details,
    )


async def test_postgres_export_workflow_handles_unexpected_insert_activity_errors(
    ateam, postgres_batch_export, interval, use_internal_stage
):
    """Test that Postgres Export Workflow can gracefully handle unexpected errors when inserting Postgres data.

    This means we do the right updates to the BatchExportRun model and ensure the workflow fails (since we
    treat this as an unexpected internal error).

    To simulate an unexpected error, we mock the `Producer.start` activity.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **postgres_batch_export.destination.config,
    )

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_POSTGRES_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[PostgresBatchExportWorkflow],
                activities=[
                    mocked_start_batch_export_run,
                    insert_into_postgres_activity,
                    insert_into_postgres_activity_from_stage,
                    insert_into_internal_stage_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with (
                    unittest.mock.patch(
                        "products.batch_exports.backend.temporal.destinations.postgres_batch_export.Producer.start",
                        side_effect=ValueError("A useful error message"),
                    ),
                    unittest.mock.patch(
                        "products.batch_exports.backend.temporal.destinations.postgres_batch_export.ProducerFromInternalStage.start",
                        side_effect=ValueError("A useful error message"),
                    ),
                ):
                    with pytest.raises(WorkflowFailureError):
                        await activity_environment.client.execute_workflow(
                            PostgresBatchExportWorkflow.run,
                            inputs,
                            id=workflow_id,
                            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                            retry_policy=RetryPolicy(maximum_attempts=1),
                        )

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "FailedRetryable"
    assert run.latest_error == "ValueError: A useful error message"
    assert run.records_completed is None


async def test_postgres_export_workflow_handles_insert_activity_non_retryable_errors(
    ateam, postgres_batch_export, interval, use_internal_stage
):
    """Test that Postgres Export Workflow can gracefully handle non-retryable errors when inserting Postgres data.

    This means we do the right updates to the BatchExportRun model and ensure the workflow succeeds (since we
    treat this as a user error).

    To simulate a user error, we mock the `Producer.start` activity.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **postgres_batch_export.destination.config,
    )

    class InsufficientPrivilege(Exception):
        pass

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_POSTGRES_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[PostgresBatchExportWorkflow],
                activities=[
                    mocked_start_batch_export_run,
                    insert_into_postgres_activity,
                    insert_into_postgres_activity_from_stage,
                    insert_into_internal_stage_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with (
                    unittest.mock.patch(
                        "products.batch_exports.backend.temporal.destinations.postgres_batch_export.Producer.start",
                        side_effect=InsufficientPrivilege("A useful error message"),
                    ),
                    unittest.mock.patch(
                        "products.batch_exports.backend.temporal.destinations.postgres_batch_export.ProducerFromInternalStage.start",
                        side_effect=InsufficientPrivilege("A useful error message"),
                    ),
                ):
                    await activity_environment.client.execute_workflow(
                        PostgresBatchExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert run.latest_error == "InsufficientPrivilege: A useful error message"
    assert run.records_completed is None


async def test_postgres_export_workflow_handles_cancellation(
    ateam, postgres_batch_export, interval, use_internal_stage
):
    """Test that Postgres Export Workflow can gracefully handle cancellations when inserting Postgres data."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **postgres_batch_export.destination.config,
    )

    @activity.defn(
        name="insert_into_postgres_activity_from_stage" if use_internal_stage else "insert_into_postgres_activity"
    )
    async def never_finish_activity(_: PostgresInsertInputs) -> str:
        while True:
            activity.heartbeat()
            await asyncio.sleep(1)

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_POSTGRES_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[PostgresBatchExportWorkflow],
                activities=[
                    mocked_start_batch_export_run,
                    never_finish_activity,
                    insert_into_internal_stage_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await activity_environment.client.start_workflow(
                    PostgresBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                await asyncio.sleep(5)
                await handle.cancel()

                with pytest.raises(WorkflowFailureError):
                    await handle.result()

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Cancelled"
    assert run.latest_error == "Cancelled"
    assert run.records_completed is None


async def test_postgres_export_workflow_with_many_files(
    clickhouse_client,
    postgres_connection,
    interval,
    postgres_batch_export,
    ateam,
    exclude_events,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    postgres_config,
    use_internal_stage,
):
    """Test Postgres Export Workflow end-to-end with multiple file uploads.

    This test overrides the chunk size and sets it to 10 bytes to trigger multiple file uploads.
    We want to assert that all files are properly copied into the table. Of course, 10 bytes limit
    means we are uploading one file at a time, which is very inefficient. For this reason, this test
    can take longer, so we keep the event count low and bump the Workflow timeout.
    """

    model = BatchExportModel(name="events", schema=None)

    workflow_id = str(uuid.uuid4())
    inputs = PostgresBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(postgres_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_model=model,
        **postgres_batch_export.destination.config,
    )

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_POSTGRES_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[PostgresBatchExportWorkflow],
                activities=[
                    start_batch_export_run,
                    insert_into_postgres_activity,
                    insert_into_postgres_activity_from_stage,
                    insert_into_internal_stage_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with override_settings(
                    BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES=10, CLICKHOUSE_MAX_BLOCK_SIZE_DEFAULT=10
                ):
                    await activity_environment.client.execute_workflow(
                        PostgresBatchExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                        execution_timeout=dt.timedelta(minutes=2),
                    )

    runs = await afetch_batch_export_runs(batch_export_id=postgres_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    await assert_clickhouse_records_in_postgres(
        postgres_connection=postgres_connection,
        clickhouse_client=clickhouse_client,
        schema_name=postgres_config["schema"],
        table_name=postgres_batch_export.destination.config["table_name"],
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        batch_export_model=model,
        sort_key="event",
    )

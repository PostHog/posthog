"""Test module covering the workflow used for batch exporting to BigQuery.

The tests are parametrized with `use_internal_stage` to cover both usage of
`insert_into_bigquery_activity` or `insert_into_bigquery_activity_from_stage` as the
main activities of the workflow.

NOTE: Once all batch exports have been moved to use the internal stage, the
`use_internal_stage` parameter can be dropped with only the `True` case remaining.
"""

import uuid
import asyncio
import datetime as dt

import pytest
import unittest.mock

from django.conf import settings
from django.test import override_settings

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.batch_exports.service import (
    BackfillDetails,
    BatchExportModel,
    BatchExportSchema,
    BigQueryBatchExportInputs,
)
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export, afetch_batch_export_runs

from products.batch_exports.backend.temporal.batch_exports import finish_batch_export_run, start_batch_export_run
from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    BigQueryBatchExportWorkflow,
    BigQueryInsertInputs,
    insert_into_bigquery_activity,
    insert_into_bigquery_activity_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import insert_into_internal_stage_activity
from products.batch_exports.backend.tests.temporal.destinations.bigquery.utils import (
    SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS,
    TEST_MODELS,
    TEST_TIME,
    assert_clickhouse_records_in_bigquery,
)
from products.batch_exports.backend.tests.temporal.utils.workflow import mocked_start_batch_export_run

pytestmark = [
    SKIP_IF_MISSING_GOOGLE_APPLICATION_CREDENTIALS,
    pytest.mark.asyncio,
    pytest.mark.django_db,
    # While we migrate to the new workflow, we need to test both new and old activities
    pytest.mark.parametrize("use_internal_stage", [False, True]),
]


@pytest.fixture
def table_id(ateam, interval):
    return f"test_workflow_table_{ateam.pk}_{interval}"


@pytest.fixture
async def bigquery_batch_export(
    ateam, table_id, bigquery_config, interval, exclude_events, use_json_type, temporal_client, bigquery_dataset
):
    destination_data = {
        "type": "BigQuery",
        "config": {
            **bigquery_config,
            "table_id": table_id,
            "dataset_id": bigquery_dataset.dataset_id,
            "exclude_events": exclude_events,
            "use_json_type": use_json_type,
        },
    }

    batch_export_data = {
        "name": "my-production-bigquery-destination",
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


@pytest.mark.parametrize("interval", ["hour", "day"])
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("use_json_type", [False, True], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_bigquery_export_workflow(
    clickhouse_client,
    bigquery_client,
    bigquery_batch_export,
    interval,
    exclude_events,
    ateam,
    table_id,
    use_json_type,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    use_internal_stage,
):
    """Test BigQuery Export Workflow end-to-end.

    The workflow should update the batch export run status to completed and produce the expected
    records to the configured BigQuery table.
    """
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    sort_key = "event"

    if isinstance(model, BatchExportModel):
        batch_export_model = model
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

    elif model is not None:
        batch_export_schema = model

    workflow_id = str(uuid.uuid4())
    inputs = BigQueryBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(bigquery_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **bigquery_batch_export.destination.config,
    )

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_BIGQUERY_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[BigQueryBatchExportWorkflow],
                activities=[
                    start_batch_export_run,
                    insert_into_bigquery_activity,
                    insert_into_bigquery_activity_from_stage,
                    insert_into_internal_stage_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await activity_environment.client.execute_workflow(
                    BigQueryBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=60),
                )

            runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
            assert len(runs) == 1

            events_to_export_created, persons_to_export_created = generate_test_data
            run = runs[0]
            assert run.status == "Completed"
            assert (
                run.records_completed == len(events_to_export_created)
                or run.records_completed == len(persons_to_export_created)
                or run.records_completed
                == len([event for event in events_to_export_created if event["properties"] is not None])
            )

            await assert_clickhouse_records_in_bigquery(
                bigquery_client=bigquery_client,
                clickhouse_client=clickhouse_client,
                table_id=table_id,
                dataset_id=bigquery_batch_export.destination.config["dataset_id"],
                team_id=ateam.pk,
                date_ranges=[(data_interval_start, data_interval_end)],
                exclude_events=exclude_events,
                include_events=None,
                batch_export_model=model,
                use_json_type=use_json_type,
                min_ingested_timestamp=TEST_TIME,
                sort_key=sort_key,
            )


@pytest.mark.parametrize("interval", ["hour"])
@pytest.mark.parametrize("exclude_events", [None], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_bigquery_export_workflow_without_events(
    clickhouse_client,
    bigquery_batch_export,
    interval,
    exclude_events,
    ateam,
    table_id,
    use_json_type,
    model: BatchExportModel | BatchExportSchema | None,
    data_interval_start,
    data_interval_end,
    use_internal_stage,
):
    """Test the BigQuery Export Workflow without any events to export.

    The workflow should update the batch export run status to completed and set 0 as `records_completed`.
    """
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    workflow_id = str(uuid.uuid4())
    inputs = BigQueryBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(bigquery_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **bigquery_batch_export.destination.config,
    )

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_BIGQUERY_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[BigQueryBatchExportWorkflow],
                activities=[
                    start_batch_export_run,
                    insert_into_bigquery_activity,
                    insert_into_bigquery_activity_from_stage,
                    insert_into_internal_stage_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await activity_environment.client.execute_workflow(
                    BigQueryBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=10),
                )

            runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
            assert len(runs) == 1

            run = runs[0]
            assert run.status == "Completed"
            assert run.records_completed == 0


@pytest.mark.parametrize(
    "data_interval_start",
    # This is set to 24 hours before the `data_interval_end` to ensure that the data created is outside the batch
    # interval.
    [TEST_TIME - dt.timedelta(hours=24)],
    indirect=True,
)
@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("use_json_type", [True], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="persons", schema=None)])
async def test_bigquery_export_workflow_backfill_earliest_persons(
    ateam,
    bigquery_client,
    bigquery_batch_export,
    clickhouse_client,
    data_interval_start,
    data_interval_end,
    generate_test_data,
    interval,
    model,
    table_id,
    use_json_type,
    use_internal_stage,
):
    """Test a `BigQueryBatchExportWorkflow` backfilling the persons model.

    We expect persons outside the batch interval to also be backfilled (i.e. persons that were updated
    more than an hour ago) when setting `is_earliest_backfill=True`.
    """
    workflow_id = str(uuid.uuid4())
    inputs = BigQueryBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(bigquery_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_model=model,
        backfill_details=BackfillDetails(
            backfill_id=None,
            start_at=None,
            end_at=data_interval_end.isoformat(),
            is_earliest_backfill=True,
        ),
        **bigquery_batch_export.destination.config,
    )
    _, persons = generate_test_data

    # Ensure some data outside batch interval has been created
    assert any(
        data_interval_end - person["_timestamp"].replace(tzinfo=dt.UTC) > dt.timedelta(hours=12) for person in persons
    )

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_BIGQUERY_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[BigQueryBatchExportWorkflow],
                activities=[
                    start_batch_export_run,
                    insert_into_bigquery_activity,
                    insert_into_bigquery_activity_from_stage,
                    insert_into_internal_stage_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await activity_environment.client.execute_workflow(
                    BigQueryBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(minutes=10),
                )

    runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"
    assert run.data_interval_start is None

    await assert_clickhouse_records_in_bigquery(
        bigquery_client=bigquery_client,
        clickhouse_client=clickhouse_client,
        table_id=table_id,
        dataset_id=bigquery_batch_export.destination.config["dataset_id"],
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=model,
        use_json_type=use_json_type,
        sort_key="person_id",
    )


async def test_bigquery_export_workflow_handles_unexpected_insert_activity_errors(
    ateam, bigquery_batch_export, interval, use_internal_stage
):
    """Test that BigQuery Export Workflow can gracefully handle unexpected errors when inserting BigQuery data.

    This means we do the right updates to the BatchExportRun model and ensure the workflow fails (since we
    treat this as an unexpected internal error).

    To simulate an unexpected error, we mock the `Producer.start` activity.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = BigQueryBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(bigquery_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **bigquery_batch_export.destination.config,
    )

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_BIGQUERY_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[BigQueryBatchExportWorkflow],
                activities=[
                    mocked_start_batch_export_run,
                    insert_into_bigquery_activity,
                    insert_into_bigquery_activity_from_stage,
                    insert_into_internal_stage_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with (
                    unittest.mock.patch(
                        "products.batch_exports.backend.temporal.destinations.bigquery_batch_export.Producer.start",
                        side_effect=RuntimeError("A useful error message"),
                    ),
                    unittest.mock.patch(
                        "products.batch_exports.backend.temporal.destinations.bigquery_batch_export.ProducerFromInternalStage.start",
                        side_effect=RuntimeError("A useful error message"),
                    ),
                ):
                    with pytest.raises(WorkflowFailureError):
                        await activity_environment.client.execute_workflow(
                            BigQueryBatchExportWorkflow.run,
                            inputs,
                            id=workflow_id,
                            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                            retry_policy=RetryPolicy(maximum_attempts=1),
                            execution_timeout=dt.timedelta(seconds=20),
                        )

    runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "FailedRetryable"
    assert run.latest_error == "RuntimeError: A useful error message"


async def test_bigquery_export_workflow_handles_insert_activity_non_retryable_errors(
    ateam, bigquery_batch_export, interval, use_internal_stage
):
    """Test that BigQuery Export Workflow can gracefully handle non-retryable errors when inserting BigQuery data.

    This means we do the right updates to the BatchExportRun model and ensure the workflow succeeds (since we
    treat this as a user error).

    To simulate a user error, we mock the `Producer.start` activity.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = BigQueryBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(bigquery_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **bigquery_batch_export.destination.config,
    )

    class RefreshError(Exception):
        pass

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_BIGQUERY_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[BigQueryBatchExportWorkflow],
                activities=[
                    mocked_start_batch_export_run,
                    insert_into_bigquery_activity,
                    insert_into_bigquery_activity_from_stage,
                    insert_into_internal_stage_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with (
                    unittest.mock.patch(
                        "products.batch_exports.backend.temporal.destinations.bigquery_batch_export.Producer.start",
                        side_effect=RefreshError("A useful error message"),
                    ),
                    unittest.mock.patch(
                        "products.batch_exports.backend.temporal.destinations.bigquery_batch_export.ProducerFromInternalStage.start",
                        side_effect=RefreshError("A useful error message"),
                    ),
                ):
                    await activity_environment.client.execute_workflow(
                        BigQueryBatchExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

    runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert run.latest_error == "RefreshError: A useful error message"
    assert run.records_completed is None


async def test_bigquery_export_workflow_handles_cancellation(
    ateam, bigquery_batch_export, interval, use_internal_stage
):
    """Test that BigQuery Export Workflow can gracefully handle cancellations when inserting BigQuery data."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = BigQueryBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(bigquery_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **bigquery_batch_export.destination.config,
    )

    @activity.defn(
        name="insert_into_bigquery_activity_from_stage" if use_internal_stage else "insert_into_bigquery_activity"
    )
    async def never_finish_activity(_: BigQueryInsertInputs) -> str:
        while True:
            activity.heartbeat()
            await asyncio.sleep(1)

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_BIGQUERY_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[BigQueryBatchExportWorkflow],
                activities=[
                    mocked_start_batch_export_run,
                    never_finish_activity,
                    insert_into_internal_stage_activity,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await activity_environment.client.start_workflow(
                    BigQueryBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                await asyncio.sleep(5)
                await handle.cancel()

                with pytest.raises(WorkflowFailureError):
                    await handle.result()

    runs = await afetch_batch_export_runs(batch_export_id=bigquery_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Cancelled"
    assert run.latest_error == "Cancelled"

import uuid
import datetime as dt

import pytest
import unittest.mock

from django.test import override_settings

from psycopg import sql
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog import constants
from posthog.batch_exports.service import BatchExportModel, BatchExportSchema, RedshiftCopyInputs
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export, afetch_batch_export_runs

from products.batch_exports.backend.temporal.batch_exports import finish_batch_export_run, start_batch_export_run
from products.batch_exports.backend.temporal.destinations.redshift_batch_export import (
    RedshiftBatchExportInputs,
    RedshiftBatchExportWorkflow,
    copy_into_redshift_activity_from_stage,
    insert_into_redshift_activity,
    insert_into_redshift_activity_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import insert_into_internal_stage_activity
from products.batch_exports.backend.tests.temporal.destinations.redshift.utils import (
    MISSING_REQUIRED_ENV_VARS,
    TEST_MODELS,
    assert_clickhouse_records_in_redshift,
)
from products.batch_exports.backend.tests.temporal.utils.s3 import delete_all_from_s3
from products.batch_exports.backend.tests.temporal.utils.workflow import mocked_start_batch_export_run

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
    # While we migrate to the new workflow, we need to test both new and old activities
    pytest.mark.parametrize("use_internal_stage", [False, True]),
]


@pytest.fixture
def table_name(ateam, interval):
    return f"test_workflow_table_{ateam.pk}_{interval}"


@pytest.fixture
def mode(request) -> str:
    try:
        return request.param
    except AttributeError:
        return "INSERT"


@pytest.fixture(autouse=True)
async def clean_up_s3_bucket(s3_client, mode, bucket_name, key_prefix):
    """Clean-up S3 bucket used in Redshift copy activity."""
    yield

    if s3_client is None or bucket_name is None or mode != "COPY":
        return

    await delete_all_from_s3(s3_client, bucket_name, key_prefix)


@pytest.fixture
async def redshift_batch_export(ateam, table_name, redshift_config, interval, exclude_events, temporal_client):
    destination_data = {
        "type": "Redshift",
        "config": {**redshift_config, "table_name": table_name, "exclude_events": exclude_events},
    }
    batch_export_data = {
        "name": "my-production-redshift-export",
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


@pytest.mark.parametrize("interval", ["hour", "day"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("mode", ["COPY", "INSERT"], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_redshift_export_workflow(
    clickhouse_client,
    redshift_config,
    psycopg_connection,
    interval,
    redshift_batch_export,
    ateam,
    exclude_events,
    table_name,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    mode,
    aws_credentials,
    bucket_name,
    bucket_region,
    key_prefix,
    use_internal_stage,
):
    """Test Redshift Export Workflow end-to-end.

    The workflow should update the batch export run status to completed and produce the expected
    records to the provided Redshift instance.
    """
    if (
        isinstance(model, BatchExportModel)
        and (model.name == "persons" or model.name == "sessions")
        and exclude_events is not None
    ):
        pytest.skip(f"Unnecessary test case as {model.name} batch export is not affected by 'exclude_events'")

    if (
        isinstance(model, BatchExportModel)
        and (model.name == "persons" or model.name == "sessions")
        and MISSING_REQUIRED_ENV_VARS
    ):
        pytest.skip(f"Batch export model {model.name} cannot be tested in PostgreSQL")

    if mode == "COPY":
        if MISSING_REQUIRED_ENV_VARS:
            pytest.skip("Testing COPY mode requires a Redshift instance")

        if use_internal_stage is False:
            pytest.skip("Testing COPY mode requires internal stage")

        if not aws_credentials or not bucket_name or not bucket_region:
            pytest.skip("Testing COPY mode requires S3 variables to be configured")

        copy_inputs = RedshiftCopyInputs(
            s3_bucket=bucket_name,
            region_name=bucket_region,
            s3_key_prefix=key_prefix,
            authorization=aws_credentials,
            bucket_credentials=aws_credentials,
        )
    else:
        copy_inputs = None

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    workflow_id = str(uuid.uuid4())
    inputs = RedshiftBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(redshift_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        mode=mode,
        copy_inputs=copy_inputs,
        **redshift_batch_export.destination.config,
    )

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_REDSHIFT_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[RedshiftBatchExportWorkflow],
                activities=[
                    start_batch_export_run,
                    insert_into_redshift_activity,
                    insert_into_internal_stage_activity,
                    insert_into_redshift_activity_from_stage,
                    copy_into_redshift_activity_from_stage,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with override_settings(BATCH_EXPORT_REDSHIFT_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
                    await activity_environment.client.execute_workflow(
                        RedshiftBatchExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                        execution_timeout=dt.timedelta(seconds=20),
                    )

    runs = await afetch_batch_export_runs(batch_export_id=redshift_batch_export.id)
    assert len(runs) == 1

    events_to_export_created, persons_to_export_created = generate_test_data

    run = runs[0]
    assert run.status == "Completed"
    assert (
        run.records_completed == len(events_to_export_created)
        or run.records_completed == len(persons_to_export_created)
        or (isinstance(model, BatchExportModel) and model.name == "sessions" and run.records_completed == 1)
    )

    sort_key = "event"
    if batch_export_model is not None:
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

    await assert_clickhouse_records_in_redshift(
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        schema_name=redshift_config["schema"],
        table_name=table_name,
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=model,
        exclude_events=exclude_events,
        sort_key=sort_key,
        copy=mode == "COPY",
    )


async def test_redshift_export_workflow_handles_unexpected_insert_activity_errors(
    event_loop, ateam, redshift_batch_export, interval, use_internal_stage
):
    """Test that Redshift Export Workflow can gracefully handle unexpected errors when inserting Redshift data.

    This means we do the right updates to the BatchExportRun model and ensure the workflow fails (since we
    treat this as an unexpected internal error).

    To simulate an unexpected error, we mock the `Producer.start` activity.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = RedshiftBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(redshift_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **redshift_batch_export.destination.config,
    )

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_REDSHIFT_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[RedshiftBatchExportWorkflow],
                activities=[
                    mocked_start_batch_export_run,
                    insert_into_redshift_activity,
                    insert_into_internal_stage_activity,
                    insert_into_redshift_activity_from_stage,
                    copy_into_redshift_activity_from_stage,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with (
                    unittest.mock.patch(
                        "products.batch_exports.backend.temporal.destinations.redshift_batch_export.Producer.start",
                        side_effect=ValueError("A useful error message"),
                    ),
                    unittest.mock.patch(
                        "products.batch_exports.backend.temporal.destinations.redshift_batch_export.ProducerFromInternalStage.start",
                        side_effect=ValueError("A useful error message"),
                    ),
                ):
                    with pytest.raises(WorkflowFailureError):
                        await activity_environment.client.execute_workflow(
                            RedshiftBatchExportWorkflow.run,
                            inputs,
                            id=workflow_id,
                            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                            retry_policy=RetryPolicy(maximum_attempts=1),
                            execution_timeout=dt.timedelta(seconds=20),
                        )

    runs = await afetch_batch_export_runs(batch_export_id=redshift_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "FailedRetryable"
    assert run.latest_error == "ValueError: A useful error message"
    assert run.records_completed is None


async def test_redshift_export_workflow_handles_insert_activity_non_retryable_errors(
    ateam, redshift_batch_export, interval, use_internal_stage
):
    """Test that Redshift Export Workflow can gracefully handle non-retryable errors when inserting Redshift data.

    This means we do the right updates to the BatchExportRun model and ensure the workflow succeeds (since we
    treat this as a user error).

    To simulate a user error, we mock the `Producer.start` activity.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = RedshiftBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(redshift_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **redshift_batch_export.destination.config,
    )

    class InsufficientPrivilege(Exception):
        pass

    use_stage_team_ids = [str(ateam.pk)] if use_internal_stage else []

    with override_settings(BATCH_EXPORT_REDSHIFT_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[RedshiftBatchExportWorkflow],
                activities=[
                    mocked_start_batch_export_run,
                    insert_into_redshift_activity,
                    insert_into_internal_stage_activity,
                    insert_into_redshift_activity_from_stage,
                    copy_into_redshift_activity_from_stage,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with (
                    unittest.mock.patch(
                        "products.batch_exports.backend.temporal.destinations.redshift_batch_export.Producer.start",
                        side_effect=InsufficientPrivilege("A useful error message"),
                    ),
                    unittest.mock.patch(
                        "products.batch_exports.backend.temporal.destinations.redshift_batch_export.ProducerFromInternalStage.start",
                        side_effect=InsufficientPrivilege("A useful error message"),
                    ),
                ):
                    await activity_environment.client.execute_workflow(
                        RedshiftBatchExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

    runs = await afetch_batch_export_runs(batch_export_id=redshift_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert run.latest_error == "InsufficientPrivilege: A useful error message"
    assert run.records_completed is None


@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None], indirect=True)
@pytest.mark.parametrize("mode", ["COPY", "INSERT"], indirect=True)
@pytest.mark.parametrize("model", [TEST_MODELS[1]])
async def test_redshift_export_workflow_handles_undefined_function_error(
    clickhouse_client,
    redshift_config,
    psycopg_connection,
    interval,
    redshift_batch_export,
    ateam,
    exclude_events,
    table_name,
    model: BatchExportModel,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    mode,
    aws_credentials,
    bucket_name,
    bucket_region,
    key_prefix,
    use_internal_stage,
):
    """Test Redshift Export Workflow can handle 'UndefinedFunction' as a non-retryable error.

    We run the workflow two times: The first time to create the target table, then we edit
    one of the columns in the target table to an invalid type, and run it again. The second
    run should fail.
    """
    if MISSING_REQUIRED_ENV_VARS:
        pytest.skip("MERGE is only available in Redshift")

    if not use_internal_stage:
        pytest.skip("MERGE of events only happens in internal stage activity")

    if mode == "COPY":
        if not aws_credentials or not bucket_name or not bucket_region:
            pytest.skip("Testing COPY mode requires S3 variables to be configured")

        copy_inputs = RedshiftCopyInputs(
            s3_bucket=bucket_name,
            region_name=bucket_region,
            s3_key_prefix=key_prefix,
            authorization=aws_credentials,
            bucket_credentials=aws_credentials,
        )
    else:
        copy_inputs = None

    batch_export_model = model

    workflow_id = str(uuid.uuid4())
    inputs = RedshiftBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(redshift_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_model=batch_export_model,
        mode=mode,
        copy_inputs=copy_inputs,
        properties_data_type="SUPER",
        **redshift_batch_export.destination.config,
    )

    use_stage_team_ids = [str(ateam.pk)]

    with override_settings(BATCH_EXPORT_REDSHIFT_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[RedshiftBatchExportWorkflow],
                activities=[
                    start_batch_export_run,
                    insert_into_redshift_activity,
                    insert_into_internal_stage_activity,
                    insert_into_redshift_activity_from_stage,
                    copy_into_redshift_activity_from_stage,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with override_settings(BATCH_EXPORT_REDSHIFT_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
                    await activity_environment.client.execute_workflow(
                        RedshiftBatchExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                        execution_timeout=dt.timedelta(seconds=20),
                    )

    runs = await afetch_batch_export_runs(batch_export_id=redshift_batch_export.id)
    assert len(runs) == 1

    events_to_export_created, persons_to_export_created = generate_test_data

    run = runs[0]
    assert run.status == "Completed"
    assert run.records_completed == len(events_to_export_created)

    sort_key = "event"

    await assert_clickhouse_records_in_redshift(
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        schema_name=redshift_config["schema"],
        table_name=table_name,
        team_id=ateam.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=model,
        exclude_events=exclude_events,
        sort_key=sort_key,
        properties_data_type="SUPER",
        copy=mode == "COPY",
    )

    async with psycopg_connection.transaction():
        async with psycopg_connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL("TRUNCATE TABLE {};").format(sql.Identifier(redshift_config["schema"], table_name))
            )

            await cursor.execute(
                sql.SQL("ALTER TABLE {} DROP COLUMN timestamp;").format(
                    sql.Identifier(redshift_config["schema"], table_name)
                )
            )
            await cursor.execute(
                sql.SQL("ALTER TABLE {} ADD COLUMN timestamp SUPER DEFAULT NULL;").format(
                    sql.Identifier(redshift_config["schema"], table_name)
                )
            )

    with override_settings(BATCH_EXPORT_REDSHIFT_USE_STAGE_TEAM_IDS=use_stage_team_ids):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[RedshiftBatchExportWorkflow],
                activities=[
                    start_batch_export_run,
                    insert_into_redshift_activity,
                    insert_into_internal_stage_activity,
                    insert_into_redshift_activity_from_stage,
                    copy_into_redshift_activity_from_stage,
                    finish_batch_export_run,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with override_settings(BATCH_EXPORT_REDSHIFT_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
                    await activity_environment.client.execute_workflow(
                        RedshiftBatchExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                        execution_timeout=dt.timedelta(seconds=20),
                    )

    runs = await afetch_batch_export_runs(batch_export_id=redshift_batch_export.id)
    assert len(runs) == 2

    failed_runs = [run for run in runs if run.status == "Failed"]
    assert len(failed_runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert run.latest_error is not None and run.latest_error.startswith("UndefinedFunction")
    assert run.records_completed is None

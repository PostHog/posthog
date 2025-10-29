import uuid
import datetime as dt

import pytest

from flaky import flaky
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog import constants
from posthog.batch_exports.service import BackfillDetails, BatchExportModel, BatchExportSchema
from posthog.temporal.tests.utils.models import afetch_batch_export_runs

from products.batch_exports.backend.temporal.batch_exports import finish_batch_export_run, start_batch_export_run
from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    COMPRESSION_EXTENSIONS,
    FILE_FORMAT_EXTENSIONS,
    SUPPORTED_COMPRESSIONS,
    S3BatchExportInputs,
    S3BatchExportWorkflow,
    insert_into_s3_activity_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import insert_into_internal_stage_activity
from products.batch_exports.backend.tests.temporal.destinations.s3.utils import (
    assert_clickhouse_records_in_s3,
    assert_metrics_in_clickhouse,
    assert_no_files_in_s3,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

TEST_DATA_INTERVAL_END = dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)

TEST_S3_MODELS: list[BatchExportModel | BatchExportSchema | None] = [
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


async def _run_s3_batch_export_workflow(
    model: BatchExportModel | BatchExportSchema | None,
    ateam,
    batch_export_id,
    s3_destination_config,
    interval,
    data_interval_start,
    data_interval_end,
    clickhouse_client,
    s3_client,
    backfill_details: BackfillDetails | None = None,
    expect_no_data: bool = False,
):
    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    exclude_events = s3_destination_config.get("exclude_events", None)
    file_format = s3_destination_config.get("file_format", "JSONLines")
    compression = s3_destination_config.get("compression", None)
    s3_key_prefix = s3_destination_config.get("prefix", None)
    bucket_name = s3_destination_config.get("bucket_name", None)

    expected_key_prefix = s3_key_prefix.format(
        table=batch_export_model.name if batch_export_model is not None else "events",
        year=data_interval_end.year,
        month=data_interval_end.strftime("%m"),
        day=data_interval_end.strftime("%d"),
        hour=data_interval_end.strftime("%H"),
        minute=data_interval_end.strftime("%M"),
        second=data_interval_end.strftime("%S"),
    )

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=batch_export_id,
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_model=batch_export_model,
        batch_export_schema=batch_export_schema,
        backfill_details=backfill_details,
        **s3_destination_config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                start_batch_export_run,
                finish_batch_export_run,
                insert_into_internal_stage_activity,
                insert_into_s3_activity_from_stage,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await activity_environment.client.execute_workflow(
                S3BatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(minutes=10),
            )

    runs = await afetch_batch_export_runs(batch_export_id=batch_export_id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    if expect_no_data:
        assert run.records_completed == 0 or (
            isinstance(model, BatchExportModel)
            and model.name == "sessions"
            and run.records_completed is not None
            and run.records_completed <= 1
        )
        assert run.bytes_exported == 0
        await assert_no_files_in_s3(s3_client, bucket_name, expected_key_prefix)
        return run

    assert run.bytes_exported is not None
    assert run.bytes_exported > 0

    sort_key = "uuid"
    if isinstance(model, BatchExportModel) and model.name == "persons":
        sort_key = "person_id"
    elif isinstance(model, BatchExportModel) and model.name == "sessions":
        sort_key = "session_id"

    await assert_metrics_in_clickhouse(
        clickhouse_client,
        batch_export_id,
        {("success", "succeeded"): 1, ("rows", "rows_exported"): run.records_completed or 0},
    )

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=s3_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=expected_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        compression=compression,
        file_format=file_format,
        sort_key=sort_key,
        backfill_details=backfill_details,
    )
    return run


class TestS3BatchExportWorkflowWithMinioBucket:
    @pytest.mark.parametrize("interval", ["hour", "day", "every 5 minutes"], indirect=True)
    @pytest.mark.parametrize("model", TEST_S3_MODELS)
    @pytest.mark.parametrize("compression", [None], indirect=True)
    @pytest.mark.parametrize("exclude_events", [None], indirect=True)
    @pytest.mark.parametrize("file_format", ["Parquet"], indirect=True)
    async def test_s3_export_workflow_with_minio_bucket_with_various_intervals_and_models(
        self,
        clickhouse_client,
        minio_client,
        ateam,
        s3_batch_export,
        bucket_name,
        interval,
        compression,
        exclude_events,
        s3_key_prefix,
        file_format,
        data_interval_start,
        data_interval_end,
        model: BatchExportModel | BatchExportSchema | None,
        generate_test_data,
    ):
        """Test S3BatchExport Workflow end-to-end by using a local MinIO bucket instead of S3.

        The workflow should update the batch export run status to completed and produce the expected
        records to the MinIO bucket.

        We use a BatchExport model to provide accurate inputs to the Workflow and because the Workflow
        will require its presence in the database when running. This model is indirectly parameterized
        by several fixtures. Refer to them for more information.
        """
        if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
            pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

        await _run_s3_batch_export_workflow(
            model=model,
            ateam=ateam,
            batch_export_id=str(s3_batch_export.id),
            s3_destination_config=s3_batch_export.destination.config,
            interval=interval,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            clickhouse_client=clickhouse_client,
            s3_client=minio_client,
        )

    @pytest.mark.parametrize("interval", ["hour"], indirect=True)
    @pytest.mark.parametrize("model", [BatchExportModel(name="events", schema=None)])
    @pytest.mark.parametrize("exclude_events", [None], indirect=True)
    @pytest.mark.parametrize("compression", [*COMPRESSION_EXTENSIONS.keys(), None], indirect=True)
    @pytest.mark.parametrize("file_format", FILE_FORMAT_EXTENSIONS.keys(), indirect=True)
    async def test_s3_export_workflow_with_minio_bucket_with_various_compression_and_file_formats(
        self,
        clickhouse_client,
        minio_client,
        ateam,
        s3_batch_export,
        bucket_name,
        interval,
        compression,
        exclude_events,
        s3_key_prefix,
        file_format,
        data_interval_start,
        data_interval_end,
        model: BatchExportModel | BatchExportSchema | None,
        generate_test_data,
    ):
        """Test S3BatchExport Workflow end-to-end by using a local MinIO bucket and various compression and file formats."""

        if compression and compression not in SUPPORTED_COMPRESSIONS[file_format]:
            pytest.skip(f"Compression {compression} is not supported for file format {file_format}")

        await _run_s3_batch_export_workflow(
            model=model,
            ateam=ateam,
            batch_export_id=str(s3_batch_export.id),
            s3_destination_config=s3_batch_export.destination.config,
            interval=interval,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            clickhouse_client=clickhouse_client,
            s3_client=minio_client,
        )

    @pytest.mark.parametrize("interval", ["hour"], indirect=True)
    @pytest.mark.parametrize("compression", [None], indirect=True)
    @pytest.mark.parametrize("file_format", ["JSONLines"], indirect=True)
    @pytest.mark.parametrize("exclude_events", [["test-exclude"]], indirect=True)
    @pytest.mark.parametrize("model", TEST_S3_MODELS)
    async def test_s3_export_workflow_with_minio_bucket_with_exclude_events(
        self,
        clickhouse_client,
        minio_client,
        ateam,
        s3_batch_export,
        bucket_name,
        interval,
        compression,
        exclude_events,
        s3_key_prefix,
        file_format,
        data_interval_start,
        data_interval_end,
        model: BatchExportModel | BatchExportSchema | None,
        generate_test_data,
    ):
        """Test S3BatchExport Workflow end-to-end by using a local MinIO bucket and excluding events."""
        if isinstance(model, BatchExportModel) and model.name in ["persons", "sessions"]:
            pytest.skip(f"Unnecessary test case as {model.name} batch export is not affected by 'exclude_events'")

        await _run_s3_batch_export_workflow(
            model=model,
            ateam=ateam,
            batch_export_id=str(s3_batch_export.id),
            s3_destination_config=s3_batch_export.destination.config,
            interval=interval,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            clickhouse_client=clickhouse_client,
            s3_client=minio_client,
        )

    @pytest.mark.parametrize(
        "data_interval_start",
        [dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(hours=24)],
        indirect=True,
    )
    @pytest.mark.parametrize("interval", ["hour"], indirect=True)
    @pytest.mark.parametrize("model", [BatchExportModel(name="persons", schema=None)])
    @flaky(max_runs=3, min_passes=1)
    async def test_s3_export_workflow_backfill_earliest_persons_with_minio_bucket(
        self,
        clickhouse_client,
        minio_client,
        ateam,
        s3_batch_export,
        bucket_name,
        interval,
        compression,
        exclude_events,
        s3_key_prefix,
        file_format,
        data_interval_start,
        data_interval_end,
        model,
        generate_test_data,
    ):
        """Test a `S3BatchExportWorkflow` backfilling the persons model.

        We expect persons outside the batch interval to also be backfilled (i.e. persons that were updated
        more than an hour ago) when setting `is_earliest_backfill=True`.
        """
        backfill_details = BackfillDetails(
            backfill_id=None,
            is_earliest_backfill=True,
            start_at=None,
            end_at=data_interval_end.isoformat(),
        )
        _, persons = generate_test_data

        assert any(
            data_interval_end - person["_timestamp"].replace(tzinfo=dt.UTC) > dt.timedelta(hours=12)
            for person in persons
        )

        await _run_s3_batch_export_workflow(
            model=model,
            ateam=ateam,
            batch_export_id=str(s3_batch_export.id),
            s3_destination_config=s3_batch_export.destination.config,
            interval=interval,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            clickhouse_client=clickhouse_client,
            s3_client=minio_client,
            backfill_details=backfill_details,
        )

    @pytest.mark.parametrize("interval", ["hour"], indirect=True)
    @pytest.mark.parametrize("compression", [None], indirect=True)
    @pytest.mark.parametrize("exclude_events", [None], indirect=True)
    @pytest.mark.parametrize("file_format", ["JSONLines"], indirect=True)
    @pytest.mark.parametrize("model", TEST_S3_MODELS)
    async def test_s3_export_workflow_with_minio_bucket_without_events(
        self,
        clickhouse_client,
        minio_client,
        ateam,
        s3_batch_export,
        bucket_name,
        interval,
        compression,
        exclude_events,
        file_format,
        s3_key_prefix,
        model,
        data_interval_start,
        data_interval_end,
    ):
        """Test S3BatchExport Workflow end-to-end without any events to export.

        The workflow should update the batch export run status to completed and set 0 as `records_completed`.
        """
        await _run_s3_batch_export_workflow(
            model=model,
            ateam=ateam,
            batch_export_id=str(s3_batch_export.id),
            s3_destination_config=s3_batch_export.destination.config,
            interval=interval,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            clickhouse_client=clickhouse_client,
            s3_client=minio_client,
            expect_no_data=True,
        )

    @pytest.mark.parametrize(
        "s3_key_prefix",
        [
            "posthog-{table}/{year}-{month}-{day}/{hour}:{minute}:{second}",
            "posthog-{table}/{hour}:{minute}:{second}/{year}-{month}-{day}",
            "posthog-{table}/{hour}:{minute}:{second}",
            "posthog/{year}-{month}-{day}/{hour}:{minute}:{second}",
            "{year}-{month}-{day}",
        ],
        indirect=True,
    )
    @pytest.mark.parametrize("model", [TEST_S3_MODELS[1], TEST_S3_MODELS[3], None])
    async def test_s3_export_workflow_with_minio_bucket_and_custom_key_prefix(
        self,
        clickhouse_client,
        ateam,
        minio_client,
        bucket_name,
        compression,
        interval,
        s3_batch_export,
        s3_key_prefix,
        data_interval_end,
        data_interval_start,
        model: BatchExportModel | BatchExportSchema | None,
        generate_test_data,
    ):
        """Test the S3BatchExport Workflow end-to-end by specifying a custom key prefix.

        This test is the same as test_s3_export_workflow_with_minio_bucket, but we create events with None as
        inserted_at to assert we properly default to _timestamp. This is relevant for rows inserted before inserted_at
        was added.
        """

        await _run_s3_batch_export_workflow(
            model=model,
            ateam=ateam,
            batch_export_id=str(s3_batch_export.id),
            s3_destination_config=s3_batch_export.destination.config,
            interval=interval,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            clickhouse_client=clickhouse_client,
            s3_client=minio_client,
        )

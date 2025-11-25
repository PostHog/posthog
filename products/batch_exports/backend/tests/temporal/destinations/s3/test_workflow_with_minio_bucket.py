import datetime as dt

import pytest

from flaky import flaky

from posthog.batch_exports.service import BackfillDetails, BatchExportModel, BatchExportSchema

from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    COMPRESSION_EXTENSIONS,
    FILE_FORMAT_EXTENSIONS,
    SUPPORTED_COMPRESSIONS,
)
from products.batch_exports.backend.tests.temporal.destinations.s3.utils import (
    TEST_S3_MODELS,
    run_s3_batch_export_workflow,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

TEST_DATA_INTERVAL_END = dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)


@pytest.mark.parametrize("interval", ["hour", "day", "every 5 minutes"], indirect=True)
@pytest.mark.parametrize("model", TEST_S3_MODELS)
@pytest.mark.parametrize("compression", [None], indirect=True)
@pytest.mark.parametrize("exclude_events", [None], indirect=True)
@pytest.mark.parametrize("file_format", ["Parquet"], indirect=True)
async def test_s3_export_workflow_with_minio_bucket_with_various_intervals_and_models(
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

    await run_s3_batch_export_workflow(
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

    await run_s3_batch_export_workflow(
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

    await run_s3_batch_export_workflow(
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
        data_interval_end - person["_timestamp"].replace(tzinfo=dt.UTC) > dt.timedelta(hours=12) for person in persons
    )

    await run_s3_batch_export_workflow(
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
    await run_s3_batch_export_workflow(
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

    await run_s3_batch_export_workflow(
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

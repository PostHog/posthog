import uuid

import pytest

from django.test import override_settings

from temporalio.testing._activity import ActivityEnvironment

from posthog.batch_exports.models import BatchExportFileDownload, BatchExportRun
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export

from products.batch_exports.backend.service import BatchExportInsertInputs, BatchExportModel, BatchExportSchema
from products.batch_exports.backend.temporal.destinations.file_download_batch_export import (
    ExportInputs,
    GenerateFileDownloadsInputs,
    S3Bucket,
    export_to_file_download_bucket_with_temporary_credentials,
    generate_file_downloads,
)
from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    COMPRESSION_EXTENSIONS,
    FILE_FORMAT_EXTENSIONS,
    SUPPORTED_COMPRESSIONS,
    s3_default_fields,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)
from products.batch_exports.backend.tests.temporal.destinations.s3.utils import (
    TEST_S3_MODELS,
    assert_clickhouse_records_in_s3,
    has_valid_credentials,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
    pytest.mark.skipif(
        not has_valid_credentials(),
        reason="AWS credentials not set in environment",
    ),
]


@pytest.mark.parametrize("compression", COMPRESSION_EXTENSIONS.keys(), indirect=True)
@pytest.mark.parametrize("model", TEST_S3_MODELS)
@pytest.mark.parametrize("file_format", FILE_FORMAT_EXTENSIONS.keys())
async def test_export_to_file_download_bucket_puts_data_into_s3(
    clickhouse_client,
    activity_environment: ActivityEnvironment,
    compression,
    exclude_events,
    file_format,
    data_interval_start,
    data_interval_end,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    ateam,
    s3_client,
    s3_bucket,
    aws_role_arn,
    region,
):
    """Test that export_to_file_download_bucket_with_temporary_credentials exports data to S3.

    The activity obtains temporary credentials via STS role assumption, constructs
    S3InsertInputs, and delegates to insert_into_s3_activity_from_stage. We verify
    the data ends up in the expected S3 location and matches what ClickHouse produces.
    """
    if compression and compression not in SUPPORTED_COMPRESSIONS[file_format]:
        pytest.skip(f"Compression {compression} is not supported for file format {file_format}")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    batch_export_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    prefix = (
        f"batch-exports/{batch_export_id}/{run_id}/{data_interval_start.isoformat()}-{data_interval_end.isoformat()}"
    )

    stage_folder = await activity_environment.run(
        insert_into_internal_stage_activity,
        BatchExportInsertIntoInternalStageInputs(
            team_id=ateam.pk,
            batch_export_id=batch_export_id,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=exclude_events,
            include_events=None,
            run_id=run_id,
            backfill_details=None,
            batch_export_model=batch_export_model,
            batch_export_schema=batch_export_schema,
            destination_default_fields=s3_default_fields(),
        ),
    )

    export_inputs = ExportInputs(
        batch_export=BatchExportInsertInputs(
            team_id=ateam.pk,
            run_id=run_id,
            stage_folder=stage_folder,
            batch_export_model=batch_export_model,
            batch_export_schema=batch_export_schema,
            batch_export_id=batch_export_id,
            exclude_events=exclude_events,
            include_events=None,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            destination_default_fields=s3_default_fields(),
        ),
        s3_bucket=S3Bucket(
            name=s3_bucket,
            region=region,
        ),
        aws_role_arn=aws_role_arn,
        compression=compression,
        file_format=file_format,
    )

    with override_settings(BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
        result = await activity_environment.run(
            export_to_file_download_bucket_with_temporary_credentials,
            export_inputs,
        )

    assert result.error is None
    assert result.records_completed is not None
    assert result.records_completed > 0
    assert result.bytes_exported is not None
    assert result.bytes_exported > 0

    events_to_export_created, persons_to_export_created = generate_test_data
    assert (
        result.records_completed == len(events_to_export_created)
        or result.records_completed == len(persons_to_export_created)
        or result.records_completed
        == len([event for event in events_to_export_created if event["properties"] is not None])
        or (isinstance(model, BatchExportModel) and model.name == "sessions" and 1 <= result.records_completed <= 2)
    )

    sort_key = "uuid"
    if isinstance(model, BatchExportModel) and model.name == "persons":
        sort_key = "person_id"
    elif isinstance(model, BatchExportModel) and model.name == "sessions":
        sort_key = "session_id"

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=s3_client,
        clickhouse_client=clickhouse_client,
        bucket_name=s3_bucket,
        key_prefix=prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        include_events=None,
        compression=compression,
        file_format=file_format,
        backfill_details=None,
        sort_key=sort_key,
    )


async def test_generate_file_downloads_creates_file_download_records(
    activity_environment: ActivityEnvironment,
    ateam,
    s3_client,
    s3_bucket,
    temporal_client,
    aws_role_arn,
    region,
):
    """Test that generate_file_downloads creates BatchExportFileDownload records for exported S3 keys.

    We first upload test files directly to S3, then run the generate_file_downloads
    activity which should call HeadObject on each key and create corresponding
    BatchExportFileDownload records in the database.
    """
    batch_export_id = str(uuid.uuid4())

    # Create a batch export in the DB since BatchExportFileDownload has a FK to it.
    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name="test-file-download-export",
        destination_data={
            # TODO: Make this a file-download batch export
            "type": "FileDownload",
            "config": {
                "file_format": "Parquet",
            },
        },
        interval="hour",
    )
    run = await BatchExportRun.objects.acreate(
        batch_export=batch_export,
        status="Completed",
        data_interval_start="2024-01-01T00:00:00",
        data_interval_end="2024-01-01T01:00:00",
    )

    prefix = f"batch-exports/{batch_export_id}/{run.id}"
    test_keys = [
        f"{prefix}/2024-01-01T00:00:00-2024-01-01T01:00:00-0.parquet",
        f"{prefix}/2024-01-01T00:00:00-2024-01-01T01:00:00-1.parquet",
    ]
    for key in test_keys:
        await s3_client.put_object(Bucket=s3_bucket, Key=key, Body=b"test-data")

    try:
        inputs = GenerateFileDownloadsInputs(
            team_id=ateam.pk,
            batch_export_id=batch_export_id,
            batch_export_run_id=str(run.id),
            s3_bucket=S3Bucket(name=s3_bucket, region=region),
            aws_role_arn=aws_role_arn,
            keys=tuple(test_keys),
        )

        file_download_ids = await activity_environment.run(
            generate_file_downloads,
            inputs,
        )

        assert len(file_download_ids) == len(test_keys)

        file_downloads = [
            file_download
            async for file_download in BatchExportFileDownload.objects.filter(
                team_id=ateam.pk, batch_export_run_id=run.id
            )
        ]
        assert len(file_downloads) == len(test_keys)

        created_keys = {fd.key for fd in file_downloads}
        assert created_keys == set(test_keys)

        for fd in file_downloads:
            assert fd.team_id == ateam.pk
            assert fd.batch_export_run_id == run.id
            assert fd.id in file_download_ids

        # Running again with the same keys should be idempotent (returns existing IDs).
        file_download_ids_again = await activity_environment.run(
            generate_file_downloads,
            inputs,
        )

        assert set(file_download_ids_again) == set(file_download_ids)

        count = await BatchExportFileDownload.objects.filter(team_id=ateam.pk, batch_export_run_id=run.id).acount()
        assert count == len(test_keys)

    finally:
        await adelete_batch_export(batch_export, temporal_client)

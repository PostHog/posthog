import uuid

import pytest

from temporalio.testing import ActivityEnvironment

from posthog.batch_exports.service import BatchExportModel
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse

from products.batch_exports.backend.temporal.destinations.azure_blob_batch_export import (
    SUPPORTED_COMPRESSIONS,
    AzureBlobInsertInputs,
    azure_blob_default_fields,
    insert_into_azure_blob_activity_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)
from products.batch_exports.backend.tests.temporal.destinations.azure_blob.utils import (
    assert_exported_data_matches_generated,
    list_blobs,
    read_manifest,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

TEST_MODELS = [
    BatchExportModel(name="events", schema=None),
    BatchExportModel(name="persons", schema=None),
    BatchExportModel(name="sessions", schema=None),
]


@pytest.mark.parametrize("model", TEST_MODELS)
async def test_activity_exports_model_to_azure_blob(
    activity_environment: ActivityEnvironment,
    ateam,
    azure_integration,
    azurite_container,
    container_name,
    blob_prefix,
    file_format,
    compression,
    data_interval_start,
    data_interval_end,
    generate_test_data,
    model: BatchExportModel,
):
    """Test that events, persons, and sessions are exported to Azure Blob Storage."""
    if compression and compression not in SUPPORTED_COMPRESSIONS[file_format]:
        pytest.skip(f"Compression {compression} is not supported for file format {file_format}")

    events_created, persons_created = generate_test_data
    batch_export_id = str(uuid.uuid4())

    if model.name == "events":
        expected_data = events_created
    elif model.name == "persons":
        expected_data = persons_created
    else:
        expected_data = events_created

    inputs = AzureBlobInsertInputs(
        team_id=ateam.pk,
        batch_export_id=batch_export_id,
        container_name=container_name,
        prefix=blob_prefix,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        file_format=file_format,
        compression=compression,
        integration_id=azure_integration.id,
        destination_default_fields=azure_blob_default_fields(),
        batch_export_model=model,
    )

    result = await run_activity(activity_environment, inputs)

    assert result.error is None
    if model.name != "sessions":
        assert result.records_completed == len(expected_data)
    else:
        # Sessions are aggregated from events, so the record count depends on
        # how events are grouped by session_id rather than a 1:1 mapping.
        # We just verify at least one session was exported.
        assert result.records_completed >= 1
    assert result.bytes_exported > 0

    await assert_exported_data_matches_generated(
        container=azurite_container,
        prefix=blob_prefix,
        generated_data=expected_data,
        file_format=file_format,
        compression=compression,
        model_name=model.name,
    )


async def test_activity_handles_empty_data_interval(
    activity_environment: ActivityEnvironment,
    ateam,
    azure_integration,
    azurite_container,
    container_name,
    blob_prefix,
):
    """Test that activity completes gracefully when no data in interval."""
    batch_export_id = str(uuid.uuid4())

    inputs = AzureBlobInsertInputs(
        team_id=ateam.pk,
        batch_export_id=batch_export_id,
        container_name=container_name,
        prefix=blob_prefix,
        data_interval_start="1990-01-01T00:00:00+00:00",
        data_interval_end="1990-01-01T01:00:00+00:00",
        file_format="JSONLines",
        compression=None,
        integration_id=azure_integration.id,
        destination_default_fields=azure_blob_default_fields(),
    )

    result = await run_activity(activity_environment, inputs)

    assert result.error is None
    assert result.records_completed == 0
    assert result.bytes_exported == 0

    blobs = await list_blobs(azurite_container, blob_prefix)
    assert len(blobs) == 0


async def test_activity_creates_multiple_files_when_splitting(
    activity_environment: ActivityEnvironment,
    clickhouse_client,
    ateam,
    azure_integration,
    azurite_container,
    container_name,
    blob_prefix,
    data_interval_start,
    data_interval_end,
):
    """Test that max_file_size_mb creates multiple blobs + manifest.json."""
    events_created, _, _ = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10000,
        count_outside_range=0,
        count_other_team=0,
        duplicate=False,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
    )

    batch_export_id = str(uuid.uuid4())
    file_format = "JSONLines"
    compression = None

    inputs = AzureBlobInsertInputs(
        team_id=ateam.pk,
        batch_export_id=batch_export_id,
        container_name=container_name,
        prefix=blob_prefix,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        file_format=file_format,
        compression=compression,
        integration_id=azure_integration.id,
        destination_default_fields=azure_blob_default_fields(),
        max_file_size_mb=1,
    )

    result = await run_activity(activity_environment, inputs)

    assert result.error is None
    assert result.records_completed == len(events_created)

    blobs = await list_blobs(azurite_container, blob_prefix)
    data_blobs = [b for b in blobs if not b.endswith("manifest.json")]

    assert len(data_blobs) > 1, f"Expected multiple files but got {len(data_blobs)}"

    manifest = await read_manifest(azurite_container, blob_prefix)
    assert manifest is not None, "Expected manifest.json when splitting files"
    assert len(manifest["files"]) == len(data_blobs)

    await assert_exported_data_matches_generated(
        container=azurite_container,
        prefix=blob_prefix,
        generated_data=events_created,
        file_format=file_format,
        compression=compression,
    )


async def run_activity(
    activity_environment: ActivityEnvironment,
    inputs: AzureBlobInsertInputs,
):
    """Run the Azure Blob export activity with internal staging."""
    assert inputs.batch_export_id is not None

    stage_folder = await activity_environment.run(
        insert_into_internal_stage_activity,
        BatchExportInsertIntoInternalStageInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=inputs.data_interval_start,
            data_interval_end=inputs.data_interval_end,
            exclude_events=inputs.exclude_events,
            include_events=None,
            run_id=None,
            backfill_details=None,
            batch_export_model=inputs.batch_export_model,
            batch_export_schema=inputs.batch_export_schema,
            destination_default_fields=azure_blob_default_fields(),
        ),
    )
    inputs.stage_folder = stage_folder

    return await activity_environment.run(
        insert_into_azure_blob_activity_from_stage,
        inputs,
    )

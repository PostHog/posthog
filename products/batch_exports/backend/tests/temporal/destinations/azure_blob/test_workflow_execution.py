import pytest

from posthog.batch_exports.service import BatchExportModel

from products.batch_exports.backend.temporal.destinations.azure_blob_batch_export import SUPPORTED_COMPRESSIONS
from products.batch_exports.backend.tests.temporal.destinations.azure_blob.utils import (
    assert_exported_data_matches_generated,
    list_blobs,
    run_azure_blob_batch_export_workflow,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

TEST_MODELS = [
    pytest.param(BatchExportModel(name="events", schema=None), id="events-model"),
    pytest.param(BatchExportModel(name="persons", schema=None), id="persons-model"),
    pytest.param(BatchExportModel(name="sessions", schema=None), id="sessions-model"),
]


@pytest.mark.parametrize("interval", ["hour", "day"], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_workflow_exports_model_successfully(
    ateam,
    azure_batch_export,
    azurite_container,
    container_name,
    blob_prefix,
    interval,
    file_format,
    compression,
    data_interval_end,
    generate_test_data,
    model: BatchExportModel,
):
    """Test that the workflow exports events, persons, or sessions to Azure Blob Storage."""
    if compression and compression not in SUPPORTED_COMPRESSIONS[file_format]:
        pytest.skip(f"Compression {compression} is not supported for file format {file_format}")

    events_created, persons_created = generate_test_data

    if model.name == "events":
        expected_data = events_created
    elif model.name == "persons":
        expected_data = persons_created
    else:
        expected_data = events_created

    run = await run_azure_blob_batch_export_workflow(
        team=ateam,
        batch_export_id=str(azure_batch_export.id),
        container_name=container_name,
        prefix=blob_prefix,
        interval=interval,
        data_interval_end=data_interval_end,
        integration_id=azure_batch_export.destination.integration.id,
        file_format=file_format,
        compression=compression,
        batch_export_model=model,
    )

    assert run.status == "Completed"
    if model.name != "sessions":
        assert run.records_completed == len(expected_data)
    else:
        assert run.records_completed is not None
        assert run.records_completed >= 1
    assert run.bytes_exported is not None
    assert run.bytes_exported > 0

    await assert_exported_data_matches_generated(
        container=azurite_container,
        prefix=blob_prefix,
        generated_data=expected_data,
        file_format=file_format,
        compression=compression,
        model_name=model.name,
    )


@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("file_format", ["JSONLines"], indirect=True)
@pytest.mark.parametrize("compression", [None], indirect=True)
async def test_workflow_handles_no_data_gracefully(
    ateam,
    azure_batch_export,
    azurite_container,
    blob_prefix,
    data_interval_end,
):
    """Test that workflow completes with 0 records when no data in interval."""
    run = await run_azure_blob_batch_export_workflow(
        team=ateam,
        batch_export_id=str(azure_batch_export.id),
        container_name=azure_batch_export.destination.config["container_name"],
        prefix=blob_prefix,
        interval="hour",
        data_interval_end=data_interval_end,
        integration_id=azure_batch_export.destination.integration.id,
        file_format="JSONLines",
        compression=None,
    )

    assert run.status == "Completed"
    assert run.records_completed == 0
    assert run.bytes_exported == 0

    blobs = await list_blobs(azurite_container, blob_prefix)
    assert len(blobs) == 0

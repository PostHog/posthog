"""E2E tests with real Azure Storage account.

These tests are skipped by default. To run them, set the following environment variables:
- AZURE_STORAGE_CONNECTION_STRING: Connection string for the Azure Storage account
- AZURE_TEST_CONTAINER: Name of the container to use for testing (must already exist)

Example:
    DEBUG=1 AZURE_STORAGE_CONNECTION_STRING='<YOUR_CONNECTION_STRING>' \
        AZURE_TEST_CONTAINER='test-exports' \
        pytest products/batch_exports/backend/tests/temporal/destinations/azure_blob/test_workflow_with_azure_account.py -v
"""

import os
import uuid
import logging

import pytest

import pytest_asyncio
from asgiref.sync import sync_to_async
from azure.storage.blob.aio import BlobServiceClient

from posthog.batch_exports.models import BatchExport, BatchExportDestination
from posthog.batch_exports.service import BatchExportModel, BatchExportSchema
from posthog.models.integration import Integration

from products.batch_exports.backend.temporal.destinations.azure_blob_batch_export import SUPPORTED_COMPRESSIONS
from products.batch_exports.backend.tests.temporal.destinations.azure_blob.utils import (
    TEST_AZURE_BLOB_MODELS,
    assert_clickhouse_records_in_azure_blob,
    run_azure_blob_batch_export_workflow,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
    pytest.mark.skipif(
        "AZURE_STORAGE_CONNECTION_STRING" not in os.environ or "AZURE_TEST_CONTAINER" not in os.environ,
        reason="Real Azure credentials not set (AZURE_STORAGE_CONNECTION_STRING and AZURE_TEST_CONTAINER required)",
    ),
]


@pytest.fixture
def container_name() -> str:
    """Use container name from environment variable."""
    return os.environ["AZURE_TEST_CONTAINER"]


@pytest.fixture
def blob_prefix() -> str:
    """Unique blob prefix per test for isolation."""
    return f"test-exports/{uuid.uuid4().hex[:8]}/"


@pytest_asyncio.fixture
async def azure_container(container_name: str, blob_prefix: str):
    """Connect to real Azure container, cleanup blobs after test."""
    connection_string = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    client = BlobServiceClient.from_connection_string(connection_string)
    container_client = client.get_container_client(container_name)

    yield container_client

    try:
        async for blob in container_client.list_blobs(name_starts_with=blob_prefix):
            await container_client.delete_blob(blob.name)
    except Exception as e:
        logging.warning("Failed to cleanup Azure container blobs with prefix %s: %s", blob_prefix, e)
    finally:
        await client.close()


@pytest_asyncio.fixture
async def azure_integration(ateam):
    """Azure Blob integration with real Azure credentials."""
    connection_string = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    integration = await sync_to_async(Integration.objects.create)(
        team=ateam,
        kind="azure-blob",
        config={},
        sensitive_config={"connection_string": connection_string},
    )
    yield integration
    await sync_to_async(integration.delete)()


@pytest_asyncio.fixture
async def azure_batch_export(
    ateam,
    azure_integration,
    container_name: str,
    blob_prefix: str,
    interval,
    file_format: str,
    compression: str | None,
):
    """Azure Blob BatchExport for workflow tests with real Azure."""
    destination = await sync_to_async(BatchExportDestination.objects.create)(
        type="AzureBlob",
        config={
            "container_name": container_name,
            "prefix": blob_prefix,
            "file_format": file_format,
            "compression": compression,
        },
        integration=azure_integration,
    )

    batch_export = await sync_to_async(BatchExport.objects.create)(
        team=ateam,
        name=f"Azure Real Test Export {uuid.uuid4().hex[:8]}",
        destination=destination,
        interval=interval,
    )

    yield batch_export

    await sync_to_async(batch_export.delete)()


@pytest.mark.parametrize("interval", ["hour", "day"], indirect=True)
@pytest.mark.parametrize("model", TEST_AZURE_BLOB_MODELS)
@pytest.mark.parametrize("file_format", ["JSONLines"], indirect=True)
@pytest.mark.parametrize("compression", [None], indirect=True)
async def test_workflow_exports_data_successfully(
    ateam,
    azure_batch_export,
    azure_container,
    container_name,
    blob_prefix,
    interval,
    file_format,
    compression,
    data_interval_start,
    data_interval_end,
    generate_test_data,
    model: BatchExportModel | BatchExportSchema | None,
):
    """Test workflow exports events, persons, or sessions to real Azure Storage."""
    batch_export_model = model if isinstance(model, BatchExportModel) else None
    batch_export_schema = model if isinstance(model, dict) else None

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
        batch_export_model=batch_export_model,
        batch_export_schema=batch_export_schema,
    )

    assert run.status == "Completed"
    assert run.records_completed is not None
    assert run.records_completed >= 1
    assert run.bytes_exported is not None
    assert run.bytes_exported > 0

    await assert_clickhouse_records_in_azure_blob(
        container=azure_container,
        key_prefix=blob_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        compression=compression,
        file_format=file_format,
    )


@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("file_format", ["JSONLines", "Parquet"], indirect=True)
@pytest.mark.parametrize("compression", [None, "gzip", "brotli", "zstd"], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="events", schema=None)])
async def test_workflow_handles_formats_and_compression(
    ateam,
    azure_batch_export,
    azure_container,
    container_name,
    blob_prefix,
    interval,
    file_format,
    compression,
    data_interval_start,
    data_interval_end,
    generate_test_data,
    model: BatchExportModel,
):
    """Test workflow handles various file formats and compression types with real Azure."""
    if compression and compression not in SUPPORTED_COMPRESSIONS[file_format]:
        pytest.skip(f"Compression {compression} is not supported for file format {file_format}")

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
    assert run.records_completed is not None
    assert run.records_completed >= 1
    assert run.bytes_exported is not None
    assert run.bytes_exported > 0

    await assert_clickhouse_records_in_azure_blob(
        container=azure_container,
        key_prefix=blob_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        compression=compression,
        file_format=file_format,
    )

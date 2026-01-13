import uuid
import logging

import pytest

import pytest_asyncio
from asgiref.sync import sync_to_async
from azure.storage.blob.aio import BlobServiceClient

from posthog.batch_exports.models import BatchExport, BatchExportDestination
from posthog.models.integration import Integration

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

# Azurite emulator default storage account credentials.
# These are public, hard-coded values from Microsoft's official Azurite documentation.
# They only work with the local Azurite emulator and cannot access real Azure storage.
# See: https://github.com/Azure/Azurite#default-storage-account
AZURITE_ACCOUNT_NAME = "devstoreaccount1"
AZURITE_ACCOUNT_KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="

AZURITE_CONNECTION_STRING = (
    f"DefaultEndpointsProtocol=http;"
    f"AccountName={AZURITE_ACCOUNT_NAME};"
    f"AccountKey={AZURITE_ACCOUNT_KEY};"
    f"BlobEndpoint=http://localhost:10000/{AZURITE_ACCOUNT_NAME};"
)

AZURITE_CONNECTION_STRING_DOCKER = AZURITE_CONNECTION_STRING.replace("localhost:10000", "objectstorage-azure:10000")


@pytest.fixture
def container_name() -> str:
    """Unique container name per test."""
    return f"test-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def blob_prefix() -> str:
    """Unique blob prefix per test."""
    return f"exports/{uuid.uuid4().hex[:8]}/"


@pytest.fixture(params=[None, "gzip", "brotli", "zstd"])
def compression(request) -> str | None:
    return request.param


@pytest.fixture(params=["JSONLines", "Parquet"])
def file_format(request) -> str:
    return request.param


@pytest_asyncio.fixture
async def azurite_container(container_name: str):
    """Create and cleanup Azurite container for test."""
    client = BlobServiceClient.from_connection_string(AZURITE_CONNECTION_STRING)
    container_client = client.get_container_client(container_name)

    await container_client.create_container()

    yield container_client

    try:
        async for blob in container_client.list_blobs():
            await container_client.delete_blob(blob.name)
        await container_client.delete_container()
    except Exception as e:
        logging.warning("Failed to cleanup Azurite container %s: %s", container_name, e)
    finally:
        await client.close()


@pytest_asyncio.fixture
async def azure_integration(ateam):
    """Azure Blob integration with Azurite credentials."""
    integration = await sync_to_async(Integration.objects.create)(
        team=ateam,
        kind="azure-blob",
        config={},
        sensitive_config={"connection_string": AZURITE_CONNECTION_STRING},
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
    """Azure Blob BatchExport for workflow tests."""
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
        name=f"Azure Test Export {uuid.uuid4().hex[:8]}",
        destination=destination,
        interval=interval,
    )

    yield batch_export

    await sync_to_async(batch_export.delete)()

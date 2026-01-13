import uuid
import logging

import pytest

from azure.storage.blob.aio import BlobServiceClient

from products.batch_exports.backend.api.destination_tests.azure_blob import AzureBlobContainerTestStep, Status
from products.batch_exports.backend.tests.temporal.destinations.azure_blob.conftest import AZURITE_CONNECTION_STRING

pytestmark = [pytest.mark.asyncio]


@pytest.fixture
def container_name() -> str:
    return f"test-{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def azurite_container(container_name: str):
    async with BlobServiceClient.from_connection_string(AZURITE_CONNECTION_STRING) as client:
        container_client = client.get_container_client(container_name)

        await container_client.create_container()

        yield container_client

        try:
            async for blob in container_client.list_blobs():
                await container_client.delete_blob(blob.name)
            await container_client.delete_container()
        except Exception as e:
            logging.warning("Failed to cleanup Azurite container %s: %s", container_name, e)


async def test_azure_blob_check_container_exists_test_step(container_name, azurite_container):
    test_step = AzureBlobContainerTestStep(
        connection_string=AZURITE_CONNECTION_STRING,
        container_name=container_name,
    )
    result = await test_step.run()

    assert result.status == Status.PASSED
    assert result.message is None


async def test_azure_blob_check_container_exists_test_step_without_container():
    test_step = AzureBlobContainerTestStep(
        connection_string=AZURITE_CONNECTION_STRING,
        container_name="nonexistent-container",
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert result.message == "Container 'nonexistent-container' does not exist"


async def test_azure_blob_check_container_invalid_connection_string():
    test_step = AzureBlobContainerTestStep(
        connection_string="invalid-connection-string",
        container_name="test-container",
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert "Invalid connection string format" in result.message


@pytest.mark.parametrize("step", [AzureBlobContainerTestStep()])
async def test_test_steps_fail_if_not_configured(step):
    result = await step.run()
    assert result.status == Status.FAILED
    assert result.message == "The test step cannot run as it's not configured."

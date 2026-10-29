import os
import uuid
import socket
import logging

import pytest
from unittest.mock import AsyncMock, Mock, patch

from django.test import override_settings

from azure.storage.blob.aio import BlobServiceClient

from products.batch_exports.backend.destination_tests.azure_blob import AzureBlobContainerTestStep, Status
from products.batch_exports.backend.temporal.destinations.azure_blob_batch_export import MalformedConnectionStringError
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
    assert result.message == f"Invalid connection string: {MalformedConnectionStringError()}"


async def test_azure_blob_check_container_emulator_connection_string():
    test_step = AzureBlobContainerTestStep(
        connection_string="UseDevelopmentStorage=true;AccountName=devstoreaccount1",
        container_name="test-container",
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert result.message is not None
    assert "Invalid connection string" in result.message


async def test_azure_blob_check_container_trailing_semicolon_connection_string(container_name, azurite_container):
    test_step = AzureBlobContainerTestStep(
        connection_string=AZURITE_CONNECTION_STRING + ";",
        container_name=container_name,
    )
    result = await test_step.run()

    assert result.status == Status.PASSED


@override_settings(FORCE_URL_VALIDATION=True, SSRF_TRUSTED_PROXY_URLS=["http://proxy.example.com:3128"])
@pytest.mark.parametrize("proxied", [False, True])
async def test_azure_blob_check_container_uses_validated_ip_without_resolving_again(proxied: bool) -> None:
    host = "storage.example.com"
    public_ip = "93.184.216.34"
    test_step = AzureBlobContainerTestStep(
        connection_string=f"AccountName=example;AccountKey=ZXhhbXBsZQ==;BlobEndpoint=https://{host}",
        container_name="test-container",
    )

    with (
        patch.dict(
            os.environ,
            {
                **{key: "" for key in os.environ if key.lower().endswith("_proxy")},
                "HTTPS_PROXY": "http://proxy.example.com:3128" if proxied else "",
            },
        ),
        patch(
            "dns.resolver.Resolver.resolve_name",
            side_effect=[
                Mock(addresses=Mock(return_value=[public_ip])),
                Mock(addresses=Mock(return_value=["127.0.0.1"])),
            ],
        ) as resolve_name,
        patch(
            "aiohttp.connector.DefaultResolver.resolve",
            new_callable=AsyncMock,
            return_value=[
                {
                    "hostname": "proxy.example.com",
                    "host": "10.0.0.2",
                    "port": 3128,
                    "family": socket.AF_INET,
                    "proto": socket.IPPROTO_TCP,
                    "flags": socket.AI_NUMERICHOST,
                }
            ],
        ) as resolve_again,
        patch(
            "aiohappyeyeballs.start_connection",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Socket connection intercepted"),
        ) as connect,
    ):
        result = await test_step.run()

    resolve_name.assert_called_once()
    assert resolve_name.call_args.args[0] == host
    if proxied:
        resolve_again.assert_awaited_once()
        assert resolve_again.call_args.args[0] == "proxy.example.com"
    else:
        resolve_again.assert_not_awaited()
    connect.assert_awaited_once()
    assert connect.call_args.kwargs["addr_infos"] == [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("10.0.0.2", 3128) if proxied else (public_ip, 443),
        )
    ]
    assert result.status == Status.FAILED
    assert result.message == "The test step failed with an unknown error: Socket connection intercepted."


@pytest.mark.parametrize("step", [AzureBlobContainerTestStep()])
async def test_test_steps_fail_if_not_configured(step):
    result = await step.run()
    assert result.status == Status.FAILED
    assert result.message == "The test step cannot run as it's not configured."

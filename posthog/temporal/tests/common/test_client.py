import pytest
from unittest import mock

from posthog.temporal.common import client as client_module
from posthog.temporal.common.client import connect

pytestmark = [pytest.mark.asyncio]

DNS_ERROR = RuntimeError(
    "Failed client connect: `transport error: error trying to connect: dns error: "
    "failed to lookup address information: Name or service not known`"
)


async def test_connect_retries_then_succeeds_on_transient_dns_failure() -> None:
    sentinel_client = object()
    connect_mock = mock.AsyncMock(side_effect=[DNS_ERROR, DNS_ERROR, sentinel_client])

    with (
        mock.patch.object(client_module.Client, "connect", connect_mock),
        mock.patch.object(client_module.asyncio, "sleep", mock.AsyncMock()) as sleep_mock,
    ):
        result = await connect("temporal", 7233, "default", settings=None, max_attempts=5)

    assert result is sentinel_client
    assert connect_mock.await_count == 3
    assert sleep_mock.await_count == 2


async def test_connect_gives_up_after_max_attempts() -> None:
    connect_mock = mock.AsyncMock(side_effect=DNS_ERROR)

    with (
        mock.patch.object(client_module.Client, "connect", connect_mock),
        mock.patch.object(client_module.asyncio, "sleep", mock.AsyncMock()),
        pytest.raises(RuntimeError, match="dns error"),
    ):
        await connect("temporal", 7233, "default", settings=None, max_attempts=3)

    assert connect_mock.await_count == 3


async def test_connect_fails_fast_by_default() -> None:
    connect_mock = mock.AsyncMock(side_effect=DNS_ERROR)

    with (
        mock.patch.object(client_module.Client, "connect", connect_mock),
        mock.patch.object(client_module.asyncio, "sleep", mock.AsyncMock()) as sleep_mock,
        pytest.raises(RuntimeError, match="dns error"),
    ):
        await connect("temporal", 7233, "default", settings=None)

    assert connect_mock.await_count == 1
    assert sleep_mock.await_count == 0

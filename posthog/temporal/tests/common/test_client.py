import pytest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized

from posthog.temporal.common.client import async_connect_with_retries

pytestmark = pytest.mark.asyncio


@parameterized.expand(
    [
        ("dns_lookup_failure", RuntimeError("failed to lookup address information: Name or service not known")),
        ("connection_refused", OSError("Connection refused")),
    ]
)
async def test_async_connect_with_retries_recovers_from_transient_failure(_name, transient_error):
    sentinel = object()
    connect_mock = AsyncMock(side_effect=[transient_error, transient_error, sentinel])

    with patch("posthog.temporal.common.client.async_connect", connect_mock):
        client = await async_connect_with_retries(initial_interval_seconds=0.0, max_interval_seconds=0.0)

    assert client is sentinel
    assert connect_mock.await_count == 3


async def test_async_connect_with_retries_reraises_after_max_attempts():
    connect_mock = AsyncMock(side_effect=RuntimeError("failed to lookup address information"))

    with patch("posthog.temporal.common.client.async_connect", connect_mock):
        with pytest.raises(RuntimeError, match="failed to lookup address information"):
            await async_connect_with_retries(max_attempts=3, initial_interval_seconds=0.0, max_interval_seconds=0.0)

    assert connect_mock.await_count == 3


async def test_async_connect_with_retries_does_not_retry_unexpected_error():
    connect_mock = AsyncMock(side_effect=ValueError("bad config"))

    with patch("posthog.temporal.common.client.async_connect", connect_mock):
        with pytest.raises(ValueError, match="bad config"):
            await async_connect_with_retries(initial_interval_seconds=0.0, max_interval_seconds=0.0)

    assert connect_mock.await_count == 1

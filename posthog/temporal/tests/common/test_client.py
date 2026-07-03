import pytest
from unittest.mock import AsyncMock, patch

from posthog.temporal.common import client as client_module
from posthog.temporal.common.client import CONNECT_MAX_ATTEMPTS, connect


@pytest.fixture
def no_backoff_sleep():
    # tenacity awaits asyncio.sleep between attempts; skip the real backoff so tests stay fast.
    with patch("asyncio.sleep", new=AsyncMock()):
        yield


@pytest.mark.asyncio
async def test_connect_retries_transient_failure_then_succeeds(no_backoff_sleep):
    sentinel = object()
    # ConnectionRefused / DNS failures surface from the Rust bridge as RuntimeError at boot.
    connect_mock = AsyncMock(side_effect=[RuntimeError("Connection refused"), RuntimeError("dns error"), sentinel])

    with patch.object(client_module.Client, "connect", connect_mock):
        result = await connect("localhost", 7233, "default", settings=None)

    assert result is sentinel
    assert connect_mock.await_count == 3


@pytest.mark.asyncio
async def test_connect_gives_up_after_max_attempts(no_backoff_sleep):
    connect_mock = AsyncMock(side_effect=RuntimeError("Connection refused"))

    with patch.object(client_module.Client, "connect", connect_mock):
        with pytest.raises(RuntimeError, match="Connection refused"):
            await connect("localhost", 7233, "default", settings=None)

    assert connect_mock.await_count == CONNECT_MAX_ATTEMPTS

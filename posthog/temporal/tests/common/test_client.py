import pytest
from unittest.mock import AsyncMock, patch

from posthog.temporal.common import client as client_module
from posthog.temporal.common.client import CONNECT_MAX_ATTEMPTS, connect


async def _connect() -> object:
    # settings=None skips the encryption codec, which needs real Django settings.
    return await connect(host="temporal", port=7233, namespace="default", settings=None)


@pytest.mark.asyncio
async def test_connect_retries_transient_failures_then_succeeds():
    """A transient ConnectionRefused on the initial connect is retried, not crashed on."""
    sentinel = object()
    attempts = [
        ConnectionRefusedError(111, "Connection refused"),
        ConnectionRefusedError(111, "Connection refused"),
        sentinel,
    ]

    async def fake_connect(*args, **kwargs):
        result = attempts.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    with (
        patch.object(client_module.Client, "connect", side_effect=fake_connect),
        patch.object(client_module.asyncio, "sleep", new=AsyncMock()) as mock_sleep,
    ):
        result = await _connect()

    assert result is sentinel
    # Backed off once per retry (two failures => two sleeps).
    assert mock_sleep.await_count == 2


@pytest.mark.asyncio
async def test_connect_raises_after_exhausting_attempts():
    """Connect gives up and re-raises once bounded attempts are exhausted."""

    async def always_refuse(*args, **kwargs):
        raise ConnectionRefusedError(111, "Connection refused")

    with (
        patch.object(client_module.Client, "connect", side_effect=always_refuse) as mock_connect,
        patch.object(client_module.asyncio, "sleep", new=AsyncMock()),
        pytest.raises(ConnectionRefusedError),
    ):
        await _connect()

    assert mock_connect.await_count == CONNECT_MAX_ATTEMPTS

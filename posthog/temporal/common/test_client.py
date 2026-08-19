import pytest
from unittest import mock

from posthog.temporal.common import client as client_module
from posthog.temporal.common.client import CONNECT_MAX_ATTEMPTS, TemporalConnectionError, connect


@pytest.fixture(autouse=True)
def _no_sleep():
    # Keep the backoff out of the test clock.
    with mock.patch.object(client_module.asyncio, "sleep", new=mock.AsyncMock()):
        yield


async def test_connect_retries_a_transient_failure_then_succeeds():
    sentinel = object()
    attempts = mock.AsyncMock(side_effect=[RuntimeError("Temporary failure in name resolution"), sentinel])

    with mock.patch.object(client_module.Client, "connect", attempts):
        result = await connect("temporal", 7233, "default", settings=None)

    assert result is sentinel
    assert attempts.await_count == 2


async def test_connect_raises_connection_error_after_exhausting_attempts():
    original = OSError("Name or service not known")
    attempts = mock.AsyncMock(side_effect=original)

    with mock.patch.object(client_module.Client, "connect", attempts):
        with pytest.raises(TemporalConnectionError) as exc_info:
            await connect("temporal", 7233, "default", settings=None)

    assert attempts.await_count == CONNECT_MAX_ATTEMPTS
    assert exc_info.value.__cause__ is original

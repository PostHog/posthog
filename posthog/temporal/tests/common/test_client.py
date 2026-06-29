import pytest
from unittest.mock import AsyncMock, patch

from posthog.temporal.common.client import connect


@pytest.mark.asyncio
async def test_connect_defaults_to_fail_fast():
    """By default connect makes a single attempt so request-path callers don't hang when Temporal is down."""
    connect_mock = AsyncMock(side_effect=RuntimeError("Failed client connect: ConnectionRefused"))

    with (
        patch("posthog.temporal.common.client.Client.connect", connect_mock),
        patch("posthog.temporal.common.client.asyncio.sleep", AsyncMock()) as sleep_mock,
    ):
        with pytest.raises(RuntimeError, match="Failed client connect"):
            await connect("localhost", 7233, "default", settings=None)

    assert connect_mock.await_count == 1
    sleep_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_retries_then_succeeds():
    """A transient connect failure at boot should be retried, not crash the caller."""
    sentinel_client = object()
    connect_mock = AsyncMock(side_effect=[RuntimeError("Failed client connect: ConnectionRefused"), sentinel_client])

    with (
        patch("posthog.temporal.common.client.Client.connect", connect_mock),
        patch("posthog.temporal.common.client.asyncio.sleep", AsyncMock()) as sleep_mock,
    ):
        client = await connect("localhost", 7233, "default", settings=None, max_attempts=3, initial_retry_delay=0.01)

    assert client is sentinel_client
    assert connect_mock.await_count == 2
    sleep_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_gives_up_after_max_attempts():
    """Once max_attempts is exhausted the final error propagates so orchestration can react."""
    connect_mock = AsyncMock(side_effect=RuntimeError("Failed client connect: ConnectionRefused"))

    with (
        patch("posthog.temporal.common.client.Client.connect", connect_mock),
        patch("posthog.temporal.common.client.asyncio.sleep", AsyncMock()) as sleep_mock,
    ):
        with pytest.raises(RuntimeError, match="Failed client connect"):
            await connect("localhost", 7233, "default", settings=None, max_attempts=3, initial_retry_delay=0.01)

    assert connect_mock.await_count == 3
    # One sleep between each attempt, but none after the final failed attempt.
    assert sleep_mock.await_count == 2


@pytest.mark.asyncio
async def test_connect_uses_capped_exponential_backoff():
    """Backoff grows exponentially from initial_retry_delay and is capped at max_retry_delay."""
    connect_mock = AsyncMock(side_effect=RuntimeError("Failed client connect: ConnectionRefused"))
    sleep_mock = AsyncMock()

    with (
        patch("posthog.temporal.common.client.Client.connect", connect_mock),
        patch("posthog.temporal.common.client.asyncio.sleep", sleep_mock),
    ):
        with pytest.raises(RuntimeError):
            await connect(
                "localhost",
                7233,
                "default",
                settings=None,
                max_attempts=6,
                initial_retry_delay=1.0,
                max_retry_delay=10.0,
                backoff_coefficient=2.0,
            )

    delays = [call.args[0] for call in sleep_mock.await_args_list]
    assert delays == [1.0, 2.0, 4.0, 8.0, 10.0]

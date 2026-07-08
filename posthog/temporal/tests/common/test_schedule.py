import pytest
from unittest.mock import AsyncMock, MagicMock

from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.schedule import a_schedule_exists


def _rpc_error(status: RPCStatusCode) -> RPCError:
    return RPCError("boom", status, b"")


def _client_with_describe(describe: AsyncMock) -> MagicMock:
    client = MagicMock()
    handle = MagicMock()
    handle.describe = describe
    client.get_schedule_handle.return_value = handle
    return client


async def test_a_schedule_exists_returns_true_when_describe_succeeds():
    client = _client_with_describe(AsyncMock(return_value=object()))

    assert await a_schedule_exists(client, "sched") is True


async def test_a_schedule_exists_returns_false_on_not_found():
    describe = AsyncMock(side_effect=_rpc_error(RPCStatusCode.NOT_FOUND))
    client = _client_with_describe(describe)

    assert await a_schedule_exists(client, "sched") is False
    describe.assert_awaited_once()


@pytest.mark.parametrize("status", [RPCStatusCode.DEADLINE_EXCEEDED, RPCStatusCode.UNAVAILABLE])
async def test_a_schedule_exists_retries_transient_error_then_succeeds(status: RPCStatusCode):
    describe = AsyncMock(side_effect=[_rpc_error(status), object()])
    client = _client_with_describe(describe)

    assert await a_schedule_exists(client, "sched", initial_backoff_seconds=0) is True
    assert describe.await_count == 2


@pytest.mark.parametrize("status", [RPCStatusCode.DEADLINE_EXCEEDED, RPCStatusCode.UNAVAILABLE])
async def test_a_schedule_exists_reraises_transient_error_after_exhausting_attempts(status: RPCStatusCode):
    describe = AsyncMock(side_effect=_rpc_error(status))
    client = _client_with_describe(describe)

    with pytest.raises(RPCError):
        await a_schedule_exists(client, "sched", max_attempts=3, initial_backoff_seconds=0)
    assert describe.await_count == 3


async def test_a_schedule_exists_reraises_non_transient_error_immediately():
    describe = AsyncMock(side_effect=_rpc_error(RPCStatusCode.PERMISSION_DENIED))
    client = _client_with_describe(describe)

    with pytest.raises(RPCError):
        await a_schedule_exists(client, "sched", initial_backoff_seconds=0)
    describe.assert_awaited_once()

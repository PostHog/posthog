import pytest
from unittest import mock

from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common import client as client_module
from posthog.temporal.common.client import connect, is_transient_temporal_error


def _rpc_error(status: RPCStatusCode) -> RPCError:
    return RPCError("boom", status, b"")


@pytest.mark.parametrize(
    "error,expected",
    [
        (RuntimeError("Failed client connect"), True),
        (_rpc_error(RPCStatusCode.UNAVAILABLE), True),
        (_rpc_error(RPCStatusCode.DEADLINE_EXCEEDED), True),
        (_rpc_error(RPCStatusCode.ABORTED), True),
        (_rpc_error(RPCStatusCode.NOT_FOUND), False),
        (_rpc_error(RPCStatusCode.ALREADY_EXISTS), False),
        (_rpc_error(RPCStatusCode.INVALID_ARGUMENT), False),
        (ValueError("nope"), False),
    ],
)
def test_is_transient_temporal_error(error: BaseException, expected: bool):
    assert is_transient_temporal_error(error) is expected


@pytest.mark.asyncio
async def test_connect_retries_transient_runtime_error():
    sentinel = object()
    attempts = {"count": 0}

    async def fake_connect(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("Failed client connect: ConnectionReset")
        return sentinel

    with (
        mock.patch.object(client_module.Client, "connect", side_effect=fake_connect),
        mock.patch.object(client_module.asyncio, "sleep", new=mock.AsyncMock()) as mock_sleep,
    ):
        result = await connect("localhost", 7233, "default", settings=None)

    assert result is sentinel
    assert attempts["count"] == 3
    assert mock_sleep.await_count == 2


@pytest.mark.asyncio
async def test_connect_gives_up_after_max_attempts():
    async def always_fail(*args, **kwargs):
        raise RuntimeError("Failed client connect: ConnectionReset")

    with (
        mock.patch.object(client_module.Client, "connect", side_effect=always_fail),
        mock.patch.object(client_module.asyncio, "sleep", new=mock.AsyncMock()) as mock_sleep,
    ):
        with pytest.raises(RuntimeError):
            await connect("localhost", 7233, "default", settings=None)

    assert mock_sleep.await_count == client_module.CONNECT_MAX_ATTEMPTS - 1

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.schedule import schedule_exists


def _rpc_error(status: RPCStatusCode) -> RPCError:
    return RPCError(status.name, status, b"")


def _client(describe_side: list[object]) -> MagicMock:
    handle = MagicMock()
    handle.describe = AsyncMock(side_effect=describe_side)
    client = MagicMock()
    client.get_schedule_handle.return_value = handle
    return client


@parameterized.expand(
    [
        ("exists", [MagicMock()], True, 1),
        ("not_found", [_rpc_error(RPCStatusCode.NOT_FOUND)], False, 1),
        ("no_poller_then_exists", [_rpc_error(RPCStatusCode.FAILED_PRECONDITION), MagicMock()], True, 2),
        (
            "unavailable_then_not_found",
            [_rpc_error(RPCStatusCode.UNAVAILABLE), _rpc_error(RPCStatusCode.NOT_FOUND)],
            False,
            2,
        ),
        (
            "transient_until_last_attempt",
            [_rpc_error(RPCStatusCode.FAILED_PRECONDITION), _rpc_error(RPCStatusCode.UNAVAILABLE), MagicMock()],
            True,
            3,
        ),
    ]
)
def test_schedule_exists_retries_transient_statuses(
    _name: str, describe_side: list[object], expected: bool, calls: int
) -> None:
    client = _client(describe_side)

    with patch("posthog.temporal.common.schedule.asyncio.sleep", new=AsyncMock()):
        assert schedule_exists(client, "some-schedule-id") is expected

    assert client.get_schedule_handle.return_value.describe.await_count == calls


@parameterized.expand(
    [
        ("permanent_status_is_not_retried", [_rpc_error(RPCStatusCode.PERMISSION_DENIED)], 1),
        ("transient_status_raises_after_three_attempts", [_rpc_error(RPCStatusCode.FAILED_PRECONDITION)] * 3, 3),
    ]
)
def test_schedule_exists_raises(_name: str, describe_side: list[object], calls: int) -> None:
    client = _client(describe_side)

    with (
        patch("posthog.temporal.common.schedule.asyncio.sleep", new=AsyncMock()),
        pytest.raises(RPCError),
    ):
        schedule_exists(client, "some-schedule-id")

    assert client.get_schedule_handle.return_value.describe.await_count == calls

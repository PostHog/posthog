import pytest
from unittest import mock

from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.schedule import a_schedule_exists


def _rpc_error(status: RPCStatusCode) -> RPCError:
    return RPCError("boom", status, b"")


def _client_with_describe_side_effect(side_effect: list | Exception) -> mock.MagicMock:
    handle = mock.MagicMock()
    handle.describe = mock.AsyncMock(side_effect=side_effect)
    client = mock.MagicMock()
    client.get_schedule_handle.return_value = handle
    return client


class TestScheduleExists:
    async def test_returns_true_when_describe_succeeds(self) -> None:
        client = _client_with_describe_side_effect([mock.MagicMock()])
        assert await a_schedule_exists(client, "some-schedule") is True

    async def test_returns_false_on_not_found(self) -> None:
        client = _client_with_describe_side_effect(_rpc_error(RPCStatusCode.NOT_FOUND))
        assert await a_schedule_exists(client, "some-schedule") is False

    async def test_retries_transient_error_then_succeeds(self) -> None:
        # A transient describe timeout must not fail the caller: retry and succeed.
        client = _client_with_describe_side_effect([_rpc_error(RPCStatusCode.CANCELLED), mock.MagicMock()])
        with mock.patch("posthog.temporal.common.schedule.asyncio.sleep", new=mock.AsyncMock()):
            assert await a_schedule_exists(client, "some-schedule") is True
        assert client.get_schedule_handle.return_value.describe.call_count == 2

    @pytest.mark.parametrize(
        "status",
        [
            RPCStatusCode.CANCELLED,
            RPCStatusCode.DEADLINE_EXCEEDED,
            RPCStatusCode.UNAVAILABLE,
            RPCStatusCode.RESOURCE_EXHAUSTED,
            RPCStatusCode.ABORTED,
        ],
    )
    async def test_reraises_transient_error_after_exhausting_retries(self, status: RPCStatusCode) -> None:
        client = _client_with_describe_side_effect(_rpc_error(status))
        with mock.patch("posthog.temporal.common.schedule.asyncio.sleep", new=mock.AsyncMock()):
            with pytest.raises(RPCError) as exc_info:
                await a_schedule_exists(client, "some-schedule")
        assert exc_info.value.status == status
        assert client.get_schedule_handle.return_value.describe.call_count == 3

    async def test_reraises_non_transient_error_immediately(self) -> None:
        client = _client_with_describe_side_effect(_rpc_error(RPCStatusCode.PERMISSION_DENIED))
        with pytest.raises(RPCError) as exc_info:
            await a_schedule_exists(client, "some-schedule")
        assert exc_info.value.status == RPCStatusCode.PERMISSION_DENIED
        assert client.get_schedule_handle.return_value.describe.call_count == 1

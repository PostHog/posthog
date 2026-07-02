from collections.abc import Awaitable, Callable

import pytest
from unittest.mock import AsyncMock, patch

from temporalio.client import Client, ScheduleAlreadyRunningError
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.schedule import _init_single_schedule, a_init_general_queue_schedules

pytestmark = pytest.mark.asyncio


def _rpc_error(status: RPCStatusCode) -> RPCError:
    return RPCError("Timeout expired", status, b"")


def _flaky_schedule(errors: list[BaseException]) -> tuple[Callable[[Client], Awaitable[None]], list[int]]:
    """A schedule callable that raises each queued error before finally succeeding."""
    calls = [0]
    queued = list(errors)

    async def schedule(_: Client) -> None:
        calls[0] += 1
        if queued:
            raise queued.pop(0)

    return schedule, calls


@pytest.fixture(autouse=True)
def _no_backoff_sleep():
    with patch("posthog.temporal.schedule.asyncio.sleep", new_callable=AsyncMock) as sleep:
        yield sleep


async def test_retries_transient_rpc_error_then_succeeds():
    schedule, calls = _flaky_schedule([_rpc_error(RPCStatusCode.DEADLINE_EXCEEDED)])

    await _init_single_schedule(schedule, client := object())  # type: ignore[arg-type]

    assert calls[0] == 2, "expected one retry after the transient timeout"
    assert client is not None


async def test_gives_up_after_max_attempts_on_persistent_transient_error():
    error = _rpc_error(RPCStatusCode.DEADLINE_EXCEEDED)
    schedule, calls = _flaky_schedule([error, error, error, error])

    with pytest.raises(RPCError):
        await _init_single_schedule(schedule, object())  # type: ignore[arg-type]

    assert calls[0] == 3, "should stop after the max attempt count"


async def test_does_not_retry_non_transient_rpc_error():
    schedule, calls = _flaky_schedule([_rpc_error(RPCStatusCode.NOT_FOUND)])

    with pytest.raises(RPCError):
        await _init_single_schedule(schedule, object())  # type: ignore[arg-type]

    assert calls[0] == 1, "a non-transient error must fail fast, not retry"


async def test_schedule_already_running_is_benign():
    schedule, calls = _flaky_schedule([ScheduleAlreadyRunningError()])

    await _init_single_schedule(schedule, object())  # type: ignore[arg-type]

    assert calls[0] == 1


async def test_one_failing_schedule_does_not_abort_the_others():
    ran: list[str] = []

    async def ok_a(_: Client) -> None:
        ran.append("a")

    async def boom(_: Client) -> None:
        raise ValueError("kaboom")

    async def ok_b(_: Client) -> None:
        ran.append("b")

    with (
        patch("posthog.temporal.schedule.async_connect", new_callable=AsyncMock),
        patch("posthog.temporal.schedule.schedules", [ok_a, boom, ok_b]),
    ):
        with pytest.raises(BaseExceptionGroup):
            await a_init_general_queue_schedules()

    assert set(ran) == {"a", "b"}, "sibling schedules must still register when one fails"

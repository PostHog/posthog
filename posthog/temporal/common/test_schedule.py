from typing import Any

import pytest
from unittest.mock import AsyncMock, patch

from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.schedule import (
    RPC_MAX_ATTEMPTS,
    a_delete_schedule,
    a_trigger_schedule,
    is_transient_rpc_error,
)

pytestmark = pytest.mark.asyncio

TIMEOUT = RPCError("Timeout expired", RPCStatusCode.DEADLINE_EXCEEDED, b"")
NOT_FOUND = RPCError("schedule not found", RPCStatusCode.NOT_FOUND, b"")


def fake_client(side_effect: list[Any], method: str = "delete") -> tuple[Any, AsyncMock]:
    call = AsyncMock(side_effect=side_effect)
    client = AsyncMock()
    client.get_schedule_handle = lambda _: AsyncMock(**{method: call})
    return client, call


@pytest.mark.parametrize(
    "side_effect,expected_calls", [([None], 1), ([TIMEOUT, None], 2), ([TIMEOUT, TIMEOUT, None], 3)]
)
async def test_transient_rpc_failure_is_retried_until_it_lands(side_effect, expected_calls):
    client, delete = fake_client(side_effect)

    with patch("posthog.temporal.common.schedule.asyncio.sleep", AsyncMock()):
        await a_delete_schedule(client, schedule_id="some-schedule")

    assert delete.await_count == expected_calls


async def test_transient_rpc_failure_raises_once_attempts_run_out():
    client, delete = fake_client([TIMEOUT] * RPC_MAX_ATTEMPTS)

    with patch("posthog.temporal.common.schedule.asyncio.sleep", AsyncMock()), pytest.raises(RPCError):
        await a_delete_schedule(client, schedule_id="some-schedule")

    assert delete.await_count == RPC_MAX_ATTEMPTS


async def test_non_transient_rpc_failure_is_not_retried():
    client, delete = fake_client([NOT_FOUND, None])

    with pytest.raises(RPCError):
        await a_delete_schedule(client, schedule_id="some-schedule")

    assert delete.await_count == 1


def test_only_transient_statuses_are_classified_as_transient():
    assert is_transient_rpc_error(TIMEOUT)
    assert not is_transient_rpc_error(NOT_FOUND)
    assert not is_transient_rpc_error(ValueError("not an RPC error"))


async def test_not_found_after_a_retried_delete_counts_as_deleted():
    # the delete landed and its response was lost, so the retry finds nothing left to delete
    client, delete = fake_client([TIMEOUT, NOT_FOUND])

    with patch("posthog.temporal.common.schedule.asyncio.sleep", AsyncMock()):
        await a_delete_schedule(client, schedule_id="some-schedule")

    assert delete.await_count == 2


async def test_not_found_on_the_first_delete_attempt_still_raises():
    # nothing was sent before it, so this is the caller's own "already gone" case to handle
    client, _ = fake_client([NOT_FOUND])

    with pytest.raises(RPCError):
        await a_delete_schedule(client, schedule_id="some-schedule")


async def test_manual_trigger_is_never_retried():
    # trigger takes no request id, so a retry past a lost response starts a second workflow run
    client, trigger = fake_client([TIMEOUT, None], method="trigger")

    with pytest.raises(RPCError):
        await a_trigger_schedule(client, schedule_id="some-schedule")

    assert trigger.await_count == 1

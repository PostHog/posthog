import asyncio
from collections.abc import AsyncIterator
from typing import Any

from unittest.mock import AsyncMock, MagicMock

from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.schedule import (
    LEGACY_SUMMARIZATION_WORKFLOW_TYPES,
    cleanup_legacy_session_summarization_schedules,
)


def _aiter(items: list[Any]) -> AsyncIterator[Any]:
    async def gen() -> AsyncIterator[Any]:
        for item in items:
            yield item

    return gen()


class _AsyncAwaitable:
    """``await`` resolves to the async iterator, matching Client.list_schedules."""

    def __init__(self, aiterable: AsyncIterator[Any]) -> None:
        self._aiterable = aiterable

    def __await__(self) -> Any:
        async def coroutine() -> AsyncIterator[Any]:
            return self._aiterable

        return coroutine().__await__()


def _make_client(running_workflows: list[Any]) -> tuple[MagicMock, list[str]]:
    """Build a mocked Client whose list_workflows records the visibility query."""
    client = MagicMock()
    client.get_schedule_handle.return_value.describe = AsyncMock(
        side_effect=RPCError("schedule not found", RPCStatusCode.NOT_FOUND, b"")
    )
    client.list_schedules.return_value = _AsyncAwaitable(_aiter([]))

    queries: list[str] = []

    def list_workflows(query: str, **kwargs: Any) -> AsyncIterator[Any]:
        queries.append(query)
        return _aiter(running_workflows)

    client.list_workflows = list_workflows

    handle = MagicMock()
    handle.terminate = AsyncMock()
    client.get_workflow_handle.return_value = handle
    return client, queries


def _expected_query() -> str:
    type_clauses = " OR ".join(f'WorkflowType = "{wt}"' for wt in LEGACY_SUMMARIZATION_WORKFLOW_TYPES)
    return f'ExecutionStatus = "Running" AND ({type_clauses})'


def test_cleanup_terminates_running_legacy_summarization_executions() -> None:
    running = [MagicMock(id=f"session-summary:group:{i}") for i in range(2)]
    client, queries = _make_client(running)

    asyncio.run(cleanup_legacy_session_summarization_schedules(client))

    assert queries == [_expected_query()]
    assert client.get_workflow_handle.call_count == 2
    for execution in running:
        client.get_workflow_handle.assert_any_call(execution.id)
    handle = client.get_workflow_handle.return_value
    assert handle.terminate.await_count == 2


def test_cleanup_termination_failure_does_not_stop_the_loop() -> None:
    running = [MagicMock(id=f"session-summary:group:{i}") for i in range(3)]
    client, _ = _make_client(running)
    handle = client.get_workflow_handle.return_value
    # Fail the first termination (e.g. the execution closed between listing and
    # terminating); the remaining two must still be terminated.
    handle.terminate = AsyncMock(side_effect=[RPCError("gone", RPCStatusCode.NOT_FOUND, b""), None, None])

    asyncio.run(cleanup_legacy_session_summarization_schedules(client))

    assert handle.terminate.await_count == 3
    client.get_workflow_handle.assert_any_call(running[1].id)
    client.get_workflow_handle.assert_any_call(running[2].id)


def test_cleanup_list_failure_does_not_raise() -> None:
    client, queries = _make_client([])

    def list_workflows(query: str, **kwargs: Any) -> AsyncIterator[Any]:
        queries.append(query)
        raise RuntimeError("visibility store unavailable")

    client.list_workflows = list_workflows

    # Must not propagate: schedule setup continues after a listing failure.
    asyncio.run(cleanup_legacy_session_summarization_schedules(client))

    assert queries == [_expected_query()]
    client.get_workflow_handle.assert_not_called()

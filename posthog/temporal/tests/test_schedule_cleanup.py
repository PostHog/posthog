import asyncio

from unittest.mock import AsyncMock, MagicMock

from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.schedule import cleanup_legacy_session_summarization_schedules


def _aiter(items: list):
    async def gen():
        for item in items:
            yield item

    return gen()


class _AsyncAwaitable:
    """``await`` resolves to the async iterator, matching Client.list_schedules."""

    def __init__(self, aiterable):
        self._aiterable = aiterable

    def __await__(self):
        async def coroutine():
            return self._aiterable

        return coroutine().__await__()


def test_cleanup_terminates_running_legacy_summarization_executions():
    running = [MagicMock(id=f"session-summary:group:{i}") for i in range(2)]
    client = MagicMock()
    client.get_schedule_handle.return_value.describe = AsyncMock(
        side_effect=RPCError("schedule not found", RPCStatusCode.NOT_FOUND, b"")
    )
    client.list_schedules.return_value = _AsyncAwaitable(_aiter([]))

    queries: list[str] = []

    def list_workflows(query: str, **kwargs):
        queries.append(query)
        return _aiter(running)

    client.list_workflows = list_workflows
    handle = MagicMock()
    handle.terminate = AsyncMock()
    client.get_workflow_handle.return_value = handle

    asyncio.run(cleanup_legacy_session_summarization_schedules(client))

    assert len(queries) == 1
    query = queries[0]
    assert 'ExecutionStatus = "Running"' in query
    for workflow_type in (
        "summarize-session",
        "summarize-session-group",
        "summarize-session-stream",
        "summarize-team-sessions",
    ):
        assert f'WorkflowType = "{workflow_type}"' in query
    assert client.get_workflow_handle.call_count == 2
    for execution in running:
        client.get_workflow_handle.assert_any_call(execution.id)
    assert handle.terminate.await_count == 2

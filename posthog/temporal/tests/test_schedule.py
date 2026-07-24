import pytest
from unittest import mock

from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.schedule import a_wait_for_namespace


class _FakeWorkflowService:
    def __init__(self, side_effects):
        self._side_effects = list(side_effects)
        self.calls = 0

    async def describe_namespace(self, req):
        self.calls += 1
        result = self._side_effects.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _client_with(side_effects):
    client = mock.Mock()
    client.workflow_service = _FakeWorkflowService(side_effects)
    return client


def _namespace_not_found():
    return RPCError("Namespace default is not found", RPCStatusCode.NOT_FOUND, b"")


@pytest.mark.asyncio
async def test_a_wait_for_namespace_retries_transient_not_found():
    client = _client_with([_namespace_not_found(), _namespace_not_found(), object()])

    await a_wait_for_namespace(client, "default", initial_delay=0, max_delay=0)

    assert client.workflow_service.calls == 3


@pytest.mark.asyncio
async def test_a_wait_for_namespace_reraises_non_not_found():
    client = _client_with([RPCError("boom", RPCStatusCode.INTERNAL, b"")])

    with pytest.raises(RPCError) as exc:
        await a_wait_for_namespace(client, "default", initial_delay=0, max_delay=0)

    assert exc.value.status == RPCStatusCode.INTERNAL
    assert client.workflow_service.calls == 1


@pytest.mark.asyncio
async def test_a_wait_for_namespace_gives_up_after_deadline():
    client = _client_with([_namespace_not_found()])

    with pytest.raises(RPCError) as exc:
        await a_wait_for_namespace(client, "default", max_wait=0, initial_delay=0, max_delay=0)

    assert exc.value.status == RPCStatusCode.NOT_FOUND

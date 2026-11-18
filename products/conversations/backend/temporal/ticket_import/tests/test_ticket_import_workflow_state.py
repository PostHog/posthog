import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from products.conversations.backend.temporal.ticket_import.workflow_state import workflow_exists, workflow_is_running

M = "products.conversations.backend.temporal.ticket_import.workflow_state"


def _client(*, status: WorkflowExecutionStatus | None = None, error: BaseException | None = None) -> MagicMock:
    handle = MagicMock()
    handle.describe = AsyncMock(return_value=MagicMock(status=status), side_effect=error)
    client = MagicMock()
    client.get_workflow_handle.return_value = handle
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client,exists,is_running",
    [
        pytest.param(_client(status=WorkflowExecutionStatus.RUNNING), True, True, id="running"),
        pytest.param(_client(status=WorkflowExecutionStatus.TERMINATED), True, False, id="terminated"),
        pytest.param(_client(status=WorkflowExecutionStatus.FAILED), True, False, id="failed"),
        pytest.param(
            _client(error=RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b"")), False, False, id="missing"
        ),
        # An unresolvable namespace answers NOT_FOUND for every workflow, so it proves nothing.
        pytest.param(
            _client(error=RPCError("namespace default not found", RPCStatusCode.NOT_FOUND, b"")),
            True,
            True,
            id="namespace",
        ),
        pytest.param(
            _client(error=RPCError("deadline exceeded", RPCStatusCode.DEADLINE_EXCEEDED, b"")), True, True, id="timeout"
        ),
        pytest.param(_client(error=ConnectionError("down")), True, True, id="unreachable"),
    ],
)
async def test_a_job_is_released_only_on_a_clear_answer_from_temporal(
    client: MagicMock, exists: bool, is_running: bool
) -> None:
    with patch(f"{M}.async_connect", new_callable=AsyncMock, return_value=client):
        assert await workflow_exists("import-1-job-1") is exists
        assert await workflow_is_running("import-1-job-1") is is_running

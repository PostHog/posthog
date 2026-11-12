import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.service import RPCError, RPCStatusCode

from products.conversations.backend.temporal.intercom_import.starter import intercom_import_workflow_exists

M = "products.conversations.backend.temporal.intercom_import.starter"


def _client_raising(exc: BaseException | None) -> MagicMock:
    handle = MagicMock()
    handle.describe = AsyncMock(side_effect=exc)
    client = MagicMock()
    client.get_workflow_handle.return_value = handle
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc,expected",
    [
        pytest.param(None, True, id="workflow_found"),
        pytest.param(RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b""), False, id="workflow_missing"),
        # An unresolvable namespace answers NOT_FOUND for every workflow, so it proves nothing.
        pytest.param(RPCError("namespace default not found", RPCStatusCode.NOT_FOUND, b""), True, id="namespace"),
        pytest.param(RPCError("deadline exceeded", RPCStatusCode.DEADLINE_EXCEEDED, b""), True, id="timeout"),
        pytest.param(ConnectionError("down"), True, id="unreachable"),
    ],
)
async def test_only_a_clean_not_found_counts_as_no_workflow(exc: BaseException | None, expected: bool) -> None:
    with patch(f"{M}.async_connect", new_callable=AsyncMock, return_value=_client_raising(exc)):
        assert await intercom_import_workflow_exists(team_id=1, job_id="job-1") is expected

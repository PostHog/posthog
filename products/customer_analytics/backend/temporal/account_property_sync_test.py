import pytest
from unittest.mock import AsyncMock, patch

from temporalio import workflow
from temporalio.exceptions import WorkflowAlreadyStartedError

from products.customer_analytics.backend.facade.temporal_contracts import DispatchAccountPropertySyncInput
from products.customer_analytics.backend.temporal.account_property_sync import (
    AccountPropertySyncInput,
    SyncWarehouseAccountPropertiesWorkflow,
    dispatch_warehouse_account_property_sync_activity,
    sync_warehouse_account_properties_activity,
)

pytestmark = pytest.mark.asyncio


async def test_dispatch_starts_missing_segment_when_its_sibling_already_runs() -> None:
    client = AsyncMock()
    client.start_workflow.side_effect = [WorkflowAlreadyStartedError("tracked", "workflow"), None]
    input = DispatchAccountPropertySyncInput(
        team_id=7,
        saved_query_id="019f0000-0000-7000-8000-000000000001",
        job_id="job-1",
    )

    with patch("products.customer_analytics.backend.temporal.account_property_sync.async_connect", return_value=client):
        await dispatch_warehouse_account_property_sync_activity(input)

    assert client.start_workflow.await_count == 2
    assert [call.args[1].segment for call in client.start_workflow.await_args_list] == ["tracked", "ignored"]


async def test_workflow_executes_one_retryable_segment_activity() -> None:
    execute_activity = AsyncMock()
    input = AccountPropertySyncInput(
        team_id=7,
        saved_query_id="019f0000-0000-7000-8000-000000000001",
        job_id="job-1",
        segment="tracked",
    )

    with patch.object(workflow, "execute_activity", new=execute_activity):
        await SyncWarehouseAccountPropertiesWorkflow().run(input)

    execute_activity.assert_awaited_once()
    assert execute_activity.await_args is not None
    assert execute_activity.await_args.args == (sync_warehouse_account_properties_activity, input)
    assert execute_activity.await_args.kwargs["retry_policy"].maximum_attempts == 5

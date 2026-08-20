import pytest
from unittest.mock import AsyncMock, patch

from temporalio import workflow

from products.customer_analytics.backend.temporal.account_property_sync import (
    AccountPropertySyncInput,
    SyncWarehouseAccountPropertiesWorkflow,
    sync_warehouse_account_properties_activity,
)

pytestmark = pytest.mark.asyncio


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

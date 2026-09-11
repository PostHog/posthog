import datetime as dt

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from temporalio.client import Client, ScheduleActionStartWorkflow, ScheduleOverlapPolicy

from products.alerts.backend.temporal.schedule import SCHEDULE_ID, create_alerts_product_check_due_schedule

MODULE = "products.alerts.backend.temporal.schedule"


@pytest.mark.asyncio
@pytest.mark.parametrize("deployment", ["US", "EU", "E2E", "", None])
async def test_schedule_does_not_access_temporal_outside_dev(deployment: str | None) -> None:
    client = MagicMock(spec=Client)
    with (
        override_settings(CLOUD_DEPLOYMENT=deployment, DEBUG=True),
        patch(f"{MODULE}.a_schedule_exists") as exists,
        patch(f"{MODULE}.a_create_schedule") as create,
        patch(f"{MODULE}.a_update_schedule") as update,
    ):
        await create_alerts_product_check_due_schedule(client)
    exists.assert_not_awaited()
    create.assert_not_awaited()
    update.assert_not_awaited()
    assert client.mock_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("already_exists", [False, True])
async def test_dev_schedule_creates_or_updates_with_bounded_policy(already_exists: bool) -> None:
    client = MagicMock(spec=Client)
    with (
        override_settings(CLOUD_DEPLOYMENT="DEV", ALERTS_PRODUCT_EVALUATION_TASK_QUEUE="evaluation-test-queue"),
        patch(f"{MODULE}.a_schedule_exists", return_value=already_exists) as exists,
        patch(f"{MODULE}.a_create_schedule") as create,
        patch(f"{MODULE}.a_update_schedule") as update,
    ):
        await create_alerts_product_check_due_schedule(client)

    exists.assert_awaited_once_with(client, SCHEDULE_ID)
    called = update if already_exists else create
    unused = create if already_exists else update
    called.assert_awaited_once()
    unused.assert_not_awaited()
    assert called.await_args is not None
    assert called.await_args.args[:2] == (client, SCHEDULE_ID)
    assert called.await_args.kwargs == ({} if already_exists else {"trigger_immediately": False})
    schedule = called.await_args.args[2]
    action = schedule.action
    assert isinstance(action, ScheduleActionStartWorkflow)
    assert action.workflow == "alerts-product-check-due"
    assert list(action.args) == [{}]
    assert action.id == SCHEDULE_ID
    assert action.task_queue == "evaluation-test-queue"
    assert action.execution_timeout == dt.timedelta(seconds=50)
    assert action.retry_policy is not None
    assert action.retry_policy.maximum_attempts == 1
    assert schedule.spec.cron_expressions == ["* * * * *"]
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert schedule.policy.catchup_window == dt.timedelta(minutes=1)
    assert not schedule.policy.pause_on_failure
    assert not schedule.state.paused

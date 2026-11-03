from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync
from temporalio.client import Schedule, ScheduleActionStartWorkflow

from posthog.temporal.health_checks.registry import HEALTH_CHECKS, ensure_registry_loaded
from posthog.temporal.health_checks.schedule import create_health_check_schedules

MODULE = "posthog.temporal.health_checks.schedule"


def test_every_scheduled_check_starts_with_its_execution_timeout() -> None:
    ensure_registry_loaded()
    scheduled = {config.name: config.execution_timeout for config in HEALTH_CHECKS.values() if config.schedule}

    with (
        patch(f"{MODULE}.a_schedule_exists", AsyncMock(return_value=False)),
        patch(f"{MODULE}.a_create_schedule", AsyncMock()) as create_schedule,
    ):
        async_to_sync(create_health_check_schedules)(MagicMock())

    timeouts: dict[str, object] = {}
    for call in create_schedule.await_args_list:
        schedule_id: str = call.args[1]
        schedule: Schedule = call.args[2]
        assert isinstance(schedule.action, ScheduleActionStartWorkflow)
        timeouts[schedule_id.removeprefix("health-check-").removesuffix("-schedule")] = (
            schedule.action.execution_timeout
        )

    assert scheduled
    assert timeouts == scheduled

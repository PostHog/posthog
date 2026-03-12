import dataclasses

from django.conf import settings

import structlog
from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleSpec

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.health_checks.models import HealthCheckWorkflowInputs
from posthog.temporal.health_checks.registry import HEALTH_CHECKS, ensure_registry_loaded

logger = structlog.get_logger(__name__)


async def create_health_check_schedules(client: Client) -> None:
    """Create or update Temporal schedules for all registered health checks.

    Called from `init_schedules()` in `posthog/temporal/schedule.py`, which runs
    as a management command during deployment (not per-pod startup). Each health
    check with a `schedule` cron expression gets a corresponding Temporal schedule
    that triggers the health-check-workflow on the general-purpose task queue.
    """
    ensure_registry_loaded()

    for config in HEALTH_CHECKS.values():
        if not config.schedule:
            continue

        schedule_id = f"health-check-{config.name}-schedule"
        workflow_inputs = HealthCheckWorkflowInputs.from_config(config)

        schedule = Schedule(
            action=ScheduleActionStartWorkflow(
                "health-check-workflow",
                dataclasses.asdict(workflow_inputs),
                id=f"health-check-{config.name}",
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            ),
            spec=ScheduleSpec(cron_expressions=[config.schedule]),
        )

        if await a_schedule_exists(client, schedule_id):
            await a_update_schedule(client, schedule_id, schedule)
        else:
            await a_create_schedule(client, schedule_id, schedule, trigger_immediately=False)

        logger.info(
            "Registered health check schedule",
            name=config.name,
            schedule_id=schedule_id,
            cron=config.schedule,
        )

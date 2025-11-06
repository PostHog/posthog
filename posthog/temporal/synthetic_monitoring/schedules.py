from datetime import timedelta

import structlog
from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

from posthog.settings import temporal as temporal_settings
from posthog.temporal.synthetic_monitoring.workflows import SyntheticMonitorSchedulerWorkflow

logger = structlog.get_logger(__name__)

SCHEDULE_ID = "synthetic-monitor-scheduler"


async def setup_synthetic_monitoring_schedule(client: Client) -> None:
    """
    Create or update the Temporal schedule for synthetic monitoring.
    This schedule runs every 60 seconds and triggers the scheduler workflow.
    """
    try:
        # Try to describe the existing schedule
        handle = client.get_schedule_handle(SCHEDULE_ID)
        await handle.describe()
        logger.info(f"Synthetic monitoring schedule '{SCHEDULE_ID}' already exists")
    except Exception:
        # Schedule doesn't exist, create it
        try:
            await client.create_schedule(
                SCHEDULE_ID,
                Schedule(
                    action=ScheduleActionStartWorkflow(
                        SyntheticMonitorSchedulerWorkflow.run,
                        id=f"{SCHEDULE_ID}-run",
                        task_queue=temporal_settings.GENERAL_PURPOSE_TASK_QUEUE,
                    ),
                    spec=ScheduleSpec(
                        intervals=[ScheduleIntervalSpec(every=timedelta(seconds=60))],
                    ),
                ),
            )
            logger.info(f"Created synthetic monitoring schedule '{SCHEDULE_ID}' (runs every 60 seconds)")
        except Exception as e:
            logger.exception(f"Failed to create synthetic monitoring schedule: {e}")
            raise

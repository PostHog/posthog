from django.conf import settings

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleSpec

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.experiments.models import (
    ExperimentRegularMetricsWorkflowInputs,
    ExperimentSavedMetricsWorkflowInputs,
)

SCHEDULE_ID_PREFIX = "experiment-regular-metrics-hour"
WORKFLOW_NAME = "experiment-regular-metrics-workflow"


async def create_experiment_regular_metrics_schedules(client: Client) -> None:
    """
    Create or update 24 schedules, one for each hour of the day.

    Each schedule runs daily at its designated hour and processes
    experiment-metrics for teams configured to recalculate at that hour.
    """
    for hour in range(24):
        schedule_id = f"{SCHEDULE_ID_PREFIX}-{hour:02d}"

        schedule = Schedule(
            action=ScheduleActionStartWorkflow(
                WORKFLOW_NAME,
                ExperimentRegularMetricsWorkflowInputs(hour=hour),
                id=f'{SCHEDULE_ID_PREFIX}-{hour:02d}-{{{{.ScheduledTime.Format "2006-01-02"}}}}',
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            ),
            spec=ScheduleSpec(cron_expressions=[f"0 {hour} * * *"]),
        )

        if await a_schedule_exists(client, schedule_id):
            await a_update_schedule(client, schedule_id, schedule)
        else:
            await a_create_schedule(client, schedule_id, schedule)


async def delete_experiment_regular_metrics_schedules(client: Client) -> None:
    """Delete all 24 experiment regular metrics schedules."""
    from posthog.temporal.common.schedule import a_delete_schedule

    for hour in range(24):
        schedule_id = f"{SCHEDULE_ID_PREFIX}-{hour:02d}"
        try:
            await a_delete_schedule(client, schedule_id)
        except Exception:
            pass  # Schedule might not exist


SAVED_SCHEDULE_ID_PREFIX = "experiment-saved-metrics-hour"
SAVED_WORKFLOW_NAME = "experiment-saved-metrics-workflow"


async def create_experiment_saved_metrics_schedules(client: Client) -> None:
    """
    Create or update 24 schedules, one for each hour of the day.

    Each schedule runs daily at its designated hour and processes
    experiment-saved metrics for teams configured to recalculate at that hour.
    """
    for hour in range(24):
        schedule_id = f"{SAVED_SCHEDULE_ID_PREFIX}-{hour:02d}"

        schedule = Schedule(
            action=ScheduleActionStartWorkflow(
                SAVED_WORKFLOW_NAME,
                ExperimentSavedMetricsWorkflowInputs(hour=hour),
                id=f'{SAVED_SCHEDULE_ID_PREFIX}-{hour:02d}-{{{{.ScheduledTime.Format "2006-01-02"}}}}',
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            ),
            spec=ScheduleSpec(cron_expressions=[f"0 {hour} * * *"]),
        )

        if await a_schedule_exists(client, schedule_id):
            await a_update_schedule(client, schedule_id, schedule)
        else:
            await a_create_schedule(client, schedule_id, schedule)


async def delete_experiment_saved_metrics_schedules(client: Client) -> None:
    """Delete all 24 experiment saved metrics schedules."""
    from posthog.temporal.common.schedule import a_delete_schedule

    for hour in range(24):
        schedule_id = f"{SAVED_SCHEDULE_ID_PREFIX}-{hour:02d}"
        try:
            await a_delete_schedule(client, schedule_id)
        except Exception:
            pass  # Schedule might not exist

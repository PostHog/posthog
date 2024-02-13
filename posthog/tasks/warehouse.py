import datetime

import structlog
from celery import shared_task

from posthog.warehouse.data_load.service import (
    cancel_external_data_workflow,
    pause_external_data_schedule,
    unpause_external_data_schedule,
)
from posthog.warehouse.models import ExternalDataJob, ExternalDataSource

logger = structlog.get_logger(__name__)

MONTHLY_LIMIT = 5_000_000


def check_synced_row_limits() -> None:
    team_ids = ExternalDataSource.objects.values_list("team", flat=True)
    for team_id in team_ids:
        check_synced_row_limits_of_team.delay(team_id)


@shared_task(ignore_result=True)
def check_synced_row_limits_of_team(team_id: int) -> None:
    logger.info("Checking synced row limits of team", team_id=team_id)

    # TODO: Can change this to be billing period based once billing is integrated
    start_of_month = datetime.datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows_synced_list = [
        x
        for x in ExternalDataJob.objects.filter(team_id=team_id, created_at__gte=start_of_month).values_list(
            "rows_synced", flat=True
        )
        if x
    ]
    total_rows_synced = sum(rows_synced_list)

    if total_rows_synced > MONTHLY_LIMIT:
        running_jobs = ExternalDataJob.objects.filter(team_id=team_id, status=ExternalDataJob.Status.RUNNING)
        for job in running_jobs:
            try:
                cancel_external_data_workflow(job.workflow_id)
            except Exception as e:
                logger.exception("Could not cancel external data workflow", exc_info=e)

            try:
                pause_external_data_schedule(job.pipeline)
            except Exception as e:
                logger.exception("Could not pause external data schedule", exc_info=e)

            job.status = ExternalDataJob.Status.CANCELLED
            job.save()

            job.pipeline.status = ExternalDataSource.Status.PAUSED
            job.pipeline.save()
    else:
        all_sources = ExternalDataSource.objects.filter(team_id=team_id, status=ExternalDataSource.Status.PAUSED)
        for source in all_sources:
            try:
                unpause_external_data_schedule(source)
            except Exception as e:
                logger.exception("Could not unpause external data schedule", exc_info=e)

            source.status = ExternalDataSource.Status.COMPLETED
            source.save()

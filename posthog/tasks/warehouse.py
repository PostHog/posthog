import datetime

import structlog
from celery import shared_task

from posthog.warehouse.models import ExternalDataJob
from posthog.ph_client import get_ph_client
from posthog.models import Team

logger = structlog.get_logger(__name__)

# TODO: adjust to whenever billing officially starts
DEFAULT_DATE_TIME = datetime.datetime(2024, 6, 1, tzinfo=datetime.UTC)


@shared_task(ignore_result=True)
def capture_workspace_rows_synced_by_team(team_id: int) -> None:
    team = Team.objects.get(pk=team_id)
    now = datetime.datetime.now(datetime.UTC)
    begin = team.external_data_workspace_last_synced_at or DEFAULT_DATE_TIME

    team.external_data_workspace_last_synced_at = now

    for job in ExternalDataJob.objects.filter(team_id=team_id, created_at__gte=begin).order_by("created_at").all():
        team.external_data_workspace_last_synced_at = job.created_at

    team.save()


@shared_task(ignore_result=True)
def validate_data_warehouse_table_columns(team_id: int, table_id: str) -> None:
    from posthog.warehouse.models import DataWarehouseTable

    ph_client = get_ph_client()

    try:
        table = DataWarehouseTable.objects.get(team_id=team_id, id=table_id)
        for column in table.columns.keys():
            table.columns[column]["valid"] = table.validate_column_type(column)
        table.save()

        if ph_client:
            ph_client.capture(team_id, "validate_data_warehouse_table_columns succeeded")
    except Exception as e:
        logger.exception(
            f"validate_data_warehouse_table_columns raised an exception for table: {table_id}",
            exc_info=e,
            team_id=team_id,
        )

        if ph_client:
            ph_client.capture(team_id, "validate_data_warehouse_table_columns errored")
    finally:
        if ph_client:
            ph_client.shutdown()

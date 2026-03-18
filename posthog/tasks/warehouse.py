import structlog
from celery import shared_task

from posthog.ph_client import get_client

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def validate_data_warehouse_table_columns(team_id: int, table_id: str) -> None:
    from products.data_warehouse.backend.models import DataWarehouseTable

    ph_client = get_client()

    try:
        table = DataWarehouseTable.objects.get(team_id=team_id, id=table_id)
        for column in table.columns.keys():
            table.columns[column]["valid"] = table.validate_column_type(column)
        table.save()

        if ph_client:
            ph_client.capture(distinct_id=team_id, event="validate_data_warehouse_table_columns succeeded")
    except Exception as e:
        logger.exception(
            f"validate_data_warehouse_table_columns raised an exception for table: {table_id}",
            exc_info=e,
            team_id=team_id,
        )

        if ph_client:
            ph_client.capture(distinct_id=team_id, event="validate_data_warehouse_table_columns errored")
    finally:
        if ph_client:
            ph_client.shutdown()

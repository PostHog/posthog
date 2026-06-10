import structlog
from celery import shared_task

from posthog.ph_client import get_client
from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
@skip_team_scope_audit
def infer_data_warehouse_saved_query_columns(team_id: int, saved_query_id: str) -> None:
    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

    try:
        view = DataWarehouseSavedQuery.objects.get(team_id=team_id, id=saved_query_id)
    except DataWarehouseSavedQuery.DoesNotExist:
        return

    try:
        view.columns = view.get_columns()
        view.external_tables = view.s3_tables
        view.save(update_fields=["columns", "external_tables"])
    except Exception as e:
        # Column inference can fail (cluster unreachable, query references a
        # missing table). The view keeps its `modified` status and stale/empty
        # columns rather than blocking the edit that scheduled this task.
        logger.exception(
            "infer_data_warehouse_saved_query_columns failed for saved query: %s",
            saved_query_id,
            exc_info=e,
            team_id=team_id,
        )


@shared_task(ignore_result=True)
@skip_team_scope_audit
def validate_data_warehouse_table_columns(team_id: int, table_id: str) -> None:
    from products.warehouse_sources.backend.models.table import DataWarehouseTable

    ph_client = get_client()

    try:
        table = DataWarehouseTable.objects.get(team_id=team_id, id=table_id)
        columns = table.columns or {}
        for column in columns.keys():
            columns[column]["valid"] = table.validate_column_type(column)
        table.columns = columns
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

from celery.utils.log import get_task_logger

from ee.clickhouse.materialized_columns.columns import (
    TRIM_AND_EXTRACT_PROPERTY,
    get_materialized_columns,
)
from posthog.client import sync_execute
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE
from posthog.clickhouse.materialized_columns import ColumnName

logger = get_task_logger(__name__)


def mark_all_materialized() -> None:
    if any_ongoing_mutations():
        logger.info("There are running mutations, skipping marking as materialized")
        return

    for (
        table,
        property_name,
        table_column,
        column_name,
    ) in get_materialized_columns_with_default_expression():
        updated_table = "sharded_events" if table == "events" else table

        # :TRICKY: On cloud, we ON CLUSTER updates to events/sharded_events but not to persons. Why? ¯\_(ツ)_/¯
        execute_on_cluster = f"ON CLUSTER '{CLICKHOUSE_CLUSTER}'" if table == "events" else ""

        sync_execute(
            f"""
            ALTER TABLE {updated_table}
            {execute_on_cluster}
            MODIFY COLUMN
            {column_name} VARCHAR MATERIALIZED {TRIM_AND_EXTRACT_PROPERTY.format(table_column=table_column)}
            """,
            {"property": property_name},
        )


def get_materialized_columns_with_default_expression():
    for table in ["events", "person"]:
        materialized_columns = get_materialized_columns(table, use_cache=False)
        for (property_name, table_column), column_name in materialized_columns.items():
            if is_default_expression(table, column_name):
                yield table, property_name, table_column, column_name


def any_ongoing_mutations() -> bool:
    running_mutations_count = sync_execute("SELECT count(*) FROM system.mutations WHERE is_done = 0")[0][0]
    return running_mutations_count > 0


def is_default_expression(table: str, column_name: ColumnName) -> bool:
    updated_table = "sharded_events" if table == "events" else table
    column_query = sync_execute(
        "SELECT default_kind FROM system.columns WHERE table = %(table)s AND name = %(name)s AND database = %(database)s",
        {"table": updated_table, "name": column_name, "database": CLICKHOUSE_DATABASE},
    )
    return len(column_query) > 0 and column_query[0][0] == "DEFAULT"

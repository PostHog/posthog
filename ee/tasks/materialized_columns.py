from collections.abc import Iterator
from dataclasses import dataclass
from celery.utils.log import get_task_logger
from clickhouse_driver import Client

from ee.clickhouse.materialized_columns.columns import MaterializedColumn, tables as table_infos
from posthog.clickhouse.client import sync_execute
from posthog.settings import CLICKHOUSE_DATABASE
from posthog.clickhouse.cluster import get_cluster
from posthog.clickhouse.materialized_columns import ColumnName, TablesWithMaterializedColumns

logger = get_task_logger(__name__)


@dataclass
class MarkMaterializedTask:
    table: str
    column: MaterializedColumn

    def execute(self, client: Client) -> None:
        expression, parameters = self.column.get_expression_and_parameters()
        client.execute(
            f"ALTER TABLE {self.table} MODIFY COLUMN {self.column.name} {self.column.type} MATERIALIZED {expression}",
            parameters,
        )


def mark_all_materialized() -> None:
    cluster = get_cluster()

    for table_name, column in get_materialized_columns_with_default_expression():
        table_info = table_infos[table_name]
        table_info.map_data_nodes(
            cluster,
            MarkMaterializedTask(
                table_info.data_table,
                column,
            ).execute,
        ).result()


def get_materialized_columns_with_default_expression() -> Iterator[tuple[str, MaterializedColumn]]:
    table_names: list[TablesWithMaterializedColumns] = ["events", "person"]
    for table_name in table_names:
        for column in MaterializedColumn.get_all(table_name):
            if is_default_expression(table_name, column.name):
                yield table_name, column


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

from datetime import timedelta

from posthog.cache_utils import cache_for
from posthog.models.property import PropertyName, TableColumn, TableWithProperties
from posthog.clickhouse.materialized_columns import ColumnName, TablesWithMaterializedColumns


@cache_for(timedelta(minutes=15))
def get_materialized_columns(
    table: TablesWithMaterializedColumns,
) -> dict[tuple[PropertyName, TableColumn], ColumnName]:
    return {}


def materialize(
    table: TableWithProperties,
    property: PropertyName,
    column_name=None,
    table_column: TableColumn = "properties",
    create_minmax_index=False,
) -> None:
    pass

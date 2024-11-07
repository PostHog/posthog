from datetime import timedelta

from posthog.cache_utils import cache_for
from posthog.models.property import PropertyName, TableColumn, TableWithProperties
from posthog.settings import EE_AVAILABLE


ColumnName = str
TablesWithMaterializedColumns = TableWithProperties

if EE_AVAILABLE:
    from ee.clickhouse.materialized_columns.columns import get_materialized_columns
else:

    def get_materialized_columns(
        table: TablesWithMaterializedColumns,
    ) -> dict[tuple[PropertyName, TableColumn], ColumnName]:
        return {}


@cache_for(timedelta(minutes=15))
def get_materialized_columns_cached(
    table: TablesWithMaterializedColumns,
) -> dict[tuple[PropertyName, TableColumn], ColumnName]:
    return get_materialized_columns(table)

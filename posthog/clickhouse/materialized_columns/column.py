from datetime import timedelta

from posthog.cache_utils import cache_for
from posthog.models.property import PropertyName, TableColumn
from posthog.clickhouse.materialized_columns import ColumnName, TablesWithMaterializedColumns


@cache_for(timedelta(minutes=15))
def get_materialized_columns(
    table: TablesWithMaterializedColumns,
) -> dict[tuple[PropertyName, TableColumn], ColumnName]:
    return {}

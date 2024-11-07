from posthog.models.property import TableWithProperties
from posthog.settings import EE_AVAILABLE

ColumnName = str
TablesWithMaterializedColumns = TableWithProperties

if EE_AVAILABLE:
    from ee.clickhouse.materialized_columns.columns import get_materialized_columns
else:
    from datetime import timedelta

    from posthog.cache_utils import cache_for
    from posthog.models.property import PropertyName, TableColumn

    @cache_for(timedelta(minutes=15))
    def get_materialized_columns(
        table: TablesWithMaterializedColumns,
    ) -> dict[tuple[PropertyName, TableColumn], ColumnName]:
        return {}

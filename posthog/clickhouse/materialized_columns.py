from typing import Protocol

from posthog.models.instance_setting import get_instance_setting
from posthog.models.property import PropertyName, TableColumn, TableWithProperties
from posthog.settings import EE_AVAILABLE

ColumnName = str
TablesWithMaterializedColumns = TableWithProperties


class MaterializedColumn(Protocol):
    name: ColumnName
    is_nullable: bool


if EE_AVAILABLE:
    from ee.clickhouse.materialized_columns.columns import get_enabled_materialized_columns

    def get_materialized_column_for_property(
        table: TablesWithMaterializedColumns, table_column: TableColumn, property_name: PropertyName
    ) -> MaterializedColumn | None:
        if not get_instance_setting("MATERIALIZED_COLUMNS_ENABLED"):
            return None

        return get_enabled_materialized_columns(table).get((property_name, table_column))
else:

    def get_materialized_column_for_property(
        table: TablesWithMaterializedColumns, table_column: TableColumn, property_name: PropertyName
    ) -> MaterializedColumn | None:
        return None

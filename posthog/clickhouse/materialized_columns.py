from collections.abc import Mapping

from posthog.clickhouse.materialized_column_types import (
    DMAT_STRING_COLUMN_NAME_PREFIX,
    MATERIALIZATION_VALID_TABLES,
    MATERIALIZED_COLUMN_NAME_PREFIXES,
    ColumnName,
    MaterializedColumn,
    TablesWithMaterializedColumns,
)
from posthog.models.instance_setting import get_instance_setting
from posthog.models.property import PropertyName, TableColumn
from posthog.property_columns import TableWithProperties
from posthog.settings import EE_AVAILABLE

__all__ = [
    "DMAT_STRING_COLUMN_NAME_PREFIX",
    "MATERIALIZATION_VALID_TABLES",
    "MATERIALIZED_COLUMN_NAME_PREFIXES",
    "ColumnName",
    "MaterializedColumn",
    "TableWithProperties",
    "TablesWithMaterializedColumns",
    "get_enabled_materialized_columns_by_table",
    "get_materialized_column_for_property",
]

if EE_AVAILABLE:
    from ee.clickhouse.materialized_columns.columns import get_enabled_materialized_columns

    def get_materialized_column_for_property(
        table: TablesWithMaterializedColumns, table_column: TableColumn, property_name: PropertyName
    ) -> MaterializedColumn | None:
        if not get_instance_setting("MATERIALIZED_COLUMNS_ENABLED"):
            return None

        return get_enabled_materialized_columns(table).get((property_name, table_column))

    def get_enabled_materialized_columns_by_table() -> Mapping[
        TablesWithMaterializedColumns, Mapping[tuple[PropertyName, TableColumn], MaterializedColumn]
    ]:
        """Enabled materialized columns for every materialization-valid table, or empty when disabled.

        Snapshot used by the HogQL property-metadata loader: fetched once per query so the engine's
        lookups are pure map reads with no Django dependency.
        """
        if not get_instance_setting("MATERIALIZED_COLUMNS_ENABLED"):
            return {}

        return {table: get_enabled_materialized_columns(table) for table in MATERIALIZATION_VALID_TABLES}
else:

    def get_materialized_column_for_property(
        table: TablesWithMaterializedColumns, table_column: TableColumn, property_name: PropertyName
    ) -> MaterializedColumn | None:
        return None

    def get_enabled_materialized_columns_by_table() -> Mapping[
        TablesWithMaterializedColumns, Mapping[tuple[PropertyName, TableColumn], MaterializedColumn]
    ]:
        return {}

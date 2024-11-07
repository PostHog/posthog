from posthog.models.property import TableWithProperties
from posthog.settings import EE_AVAILABLE

ColumnName = str
TablesWithMaterializedColumns = TableWithProperties

if EE_AVAILABLE:
    from ee.clickhouse.materialized_columns.columns import get_materialized_columns, materialize
else:
    from .column import get_materialized_columns, materialize

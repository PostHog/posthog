from posthog.clickhouse.client.migration_tools import NodeRole, run_sql_with_exceptions
from posthog.clickhouse.warehouse_object_reads import (
    WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE_SQL,
    WAREHOUSE_OBJECT_READS_DAILY_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(WAREHOUSE_OBJECT_READS_DAILY_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE_SQL(), node_roles=[NodeRole.DATA]),
]

from posthog.clickhouse.client.migration_tools import NodeRole, run_sql_with_exceptions
from posthog.clickhouse.warehouse_object_reads import (
    DISTRIBUTED_WAREHOUSE_OBJECT_READS_DAILY_TABLE_SQL,
    SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE_SQL,
    SHARDED_WAREHOUSE_OBJECT_READS_DAILY_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(SHARDED_WAREHOUSE_OBJECT_READS_DAILY_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(
        DISTRIBUTED_WAREHOUSE_OBJECT_READS_DAILY_TABLE_SQL(), node_roles=[NodeRole.AUX, NodeRole.DATA]
    ),
]

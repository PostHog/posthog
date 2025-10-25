from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.heatmaps.sql import (
    DISTRIBUTED_HEATMAPS_TABLE_SQL,
    HEATMAPS_TABLE_MV_SQL,
    HEATMAPS_TABLE_SQL,
    KAFKA_HEATMAPS_TABLE_SQL,
    WRITABLE_HEATMAPS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(WRITABLE_HEATMAPS_TABLE_SQL(), node_roles=NodeRole.DATA),
    run_sql_with_exceptions(DISTRIBUTED_HEATMAPS_TABLE_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(HEATMAPS_TABLE_SQL(), node_roles=NodeRole.DATA),
    run_sql_with_exceptions(KAFKA_HEATMAPS_TABLE_SQL(), node_roles=NodeRole.DATA),
    run_sql_with_exceptions(HEATMAPS_TABLE_MV_SQL(), node_roles=NodeRole.DATA),
]

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.heatmaps.sql import (
    DROP_HEATMAPS_TABLE_MV_SQL,
    DROP_KAFKA_HEATMAPS_TABLE_SQL,
    DROP_WRITABLE_HEATMAPS_TABLE_SQL,
    HEATMAPS_TABLE_MV_SQL,
    KAFKA_HEATMAPS_TABLE_SQL,
    WRITABLE_HEATMAPS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(DROP_HEATMAPS_TABLE_MV_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_HEATMAPS_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_WRITABLE_HEATMAPS_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(KAFKA_HEATMAPS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(HEATMAPS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(WRITABLE_HEATMAPS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_MEDIUM]),
]

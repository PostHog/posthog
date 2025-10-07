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
from posthog.models.app_metrics.sql import (
    APP_METRICS_MV_TABLE_SQL,
    DROP_APP_METRICS_MV_TABLE_SQL,
    DROP_KAFKA_APP_METRICS_TABLE_SQL,
    KAFKA_APP_METRICS_TABLE_SQL,
    WRITABLE_APP_METRICS_TABLE_SQL,
)
from posthog.models.app_metrics2.sql import (
    APP_METRICS2_MV_TABLE_SQL,
    DROP_APP_METRICS2_MV_TABLE_SQL,
    DROP_KAFKA_APP_METRICS2_TABLE_SQL,
    KAFKA_APP_METRICS2_TABLE_SQL,
    WRITABLE_APP_METRICS2_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(DROP_HEATMAPS_TABLE_MV_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_HEATMAPS_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_WRITABLE_HEATMAPS_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(KAFKA_HEATMAPS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(WRITABLE_HEATMAPS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(HEATMAPS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(DROP_APP_METRICS2_MV_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_APP_METRICS2_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(KAFKA_APP_METRICS2_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(WRITABLE_APP_METRICS2_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(APP_METRICS2_MV_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(DROP_APP_METRICS_MV_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_APP_METRICS_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(KAFKA_APP_METRICS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(WRITABLE_APP_METRICS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(APP_METRICS_MV_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
]

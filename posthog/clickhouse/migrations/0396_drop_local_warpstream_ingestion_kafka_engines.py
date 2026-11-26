from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.log_entries import DROP_KAFKA_LOG_ENTRIES_WS_TABLE_SQL, DROP_LOG_ENTRIES_WS_MV_SQL
from posthog.models.app_metrics2.sql import DROP_APP_METRICS2_WS_MV_TABLE_SQL, DROP_KAFKA_APP_METRICS2_WS_TABLE_SQL
from posthog.models.tophog.sql import DROP_KAFKA_TOPHOG_WS_TABLE_SQL, DROP_TOPHOG_WS_MV_SQL
from posthog.run_mode import run_mode

# Outside cloud, the msk_cluster and warpstream_ingestion named collections point at the
# same broker, so the WarpStream Kafka tables from 0227 consume every log_entries,
# app_metrics2 and tophog message a second time into the same target table. 0227 is
# cloud-only; this drops what it created on installs that ran it before that guard.
# Each MV goes before its Kafka table, so nothing writes from a dropped source.

operations = (
    []
    if run_mode().is_deployed_cloud
    else [
        run_sql_with_exceptions(DROP_LOG_ENTRIES_WS_MV_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
        run_sql_with_exceptions(DROP_KAFKA_LOG_ENTRIES_WS_TABLE_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
        run_sql_with_exceptions(DROP_APP_METRICS2_WS_MV_TABLE_SQL, node_roles=[NodeRole.INGESTION_MEDIUM]),
        run_sql_with_exceptions(DROP_KAFKA_APP_METRICS2_WS_TABLE_SQL, node_roles=[NodeRole.INGESTION_MEDIUM]),
        run_sql_with_exceptions(DROP_TOPHOG_WS_MV_SQL, node_roles=[NodeRole.INGESTION_MEDIUM]),
        run_sql_with_exceptions(DROP_KAFKA_TOPHOG_WS_TABLE_SQL, node_roles=[NodeRole.INGESTION_MEDIUM]),
    ]
)

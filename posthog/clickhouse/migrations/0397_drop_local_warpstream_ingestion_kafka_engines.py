from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.log_entries import DROP_KAFKA_LOG_ENTRIES_WS_TABLE_SQL, DROP_LOG_ENTRIES_WS_MV_SQL
from posthog.models.app_metrics2.sql import DROP_APP_METRICS2_WS_MV_TABLE_SQL, DROP_KAFKA_APP_METRICS2_WS_TABLE_SQL
from posthog.models.tophog.sql import DROP_KAFKA_TOPHOG_WS_TABLE_SQL, DROP_TOPHOG_WS_MV_SQL
from posthog.run_mode import RunMode, run_mode

operations = (
    [
        run_sql_with_exceptions(DROP_LOG_ENTRIES_WS_MV_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
        run_sql_with_exceptions(DROP_KAFKA_LOG_ENTRIES_WS_TABLE_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
        run_sql_with_exceptions(DROP_APP_METRICS2_WS_MV_TABLE_SQL, node_roles=[NodeRole.INGESTION_MEDIUM]),
        run_sql_with_exceptions(DROP_KAFKA_APP_METRICS2_WS_TABLE_SQL, node_roles=[NodeRole.INGESTION_MEDIUM]),
        run_sql_with_exceptions(DROP_TOPHOG_WS_MV_SQL, node_roles=[NodeRole.INGESTION_MEDIUM]),
        run_sql_with_exceptions(DROP_KAFKA_TOPHOG_WS_TABLE_SQL, node_roles=[NodeRole.INGESTION_MEDIUM]),
    ]
    if run_mode() in (RunMode.LOCAL, RunMode.E2E)
    else []
)

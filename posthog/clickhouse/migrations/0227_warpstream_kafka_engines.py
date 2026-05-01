from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.log_entries import KAFKA_LOG_ENTRIES_WS_TABLE_SQL, LOG_ENTRIES_WS_MV_SQL
from posthog.models.app_metrics2.sql import APP_METRICS2_WS_MV_TABLE_SQL, KAFKA_APP_METRICS2_WS_TABLE_SQL
from posthog.models.tophog.sql import KAFKA_TOPHOG_WS_TABLE_SQL, TOPHOG_WS_MV_SQL

# Migration to create WarpStream Kafka engine tables for log_entries, app_metrics2, and tophog.
#
# These tables coexist alongside the existing MSK Kafka engine tables, reading from
# the same topics but via the warpstream_ingestion named collection. Each has its own
# consumer group to avoid conflicts with the MSK tables.
#
# New tables:
# - kafka_log_entries_ws + log_entries_ws_mv (INGESTION_SMALL)
# - kafka_app_metrics2_ws + app_metrics2_ws_mv (INGESTION_MEDIUM)
# - kafka_tophog_ws + tophog_ws_mv (INGESTION_MEDIUM)

operations = [
    # log_entries (INGESTION_SMALL, matching existing MSK table)
    run_sql_with_exceptions(
        KAFKA_LOG_ENTRIES_WS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        LOG_ENTRIES_WS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # app_metrics2 (INGESTION_MEDIUM, matching existing MSK table)
    run_sql_with_exceptions(
        KAFKA_APP_METRICS2_WS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        APP_METRICS2_WS_MV_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    # tophog (INGESTION_MEDIUM, matching existing MSK table)
    run_sql_with_exceptions(
        KAFKA_TOPHOG_WS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        TOPHOG_WS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
]

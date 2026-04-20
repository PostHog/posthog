from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.ingestion_warnings.sql import INGESTION_WARNINGS_WS_MV_SQL, KAFKA_INGESTION_WARNINGS_WS_TABLE_SQL

# Migration to create a WarpStream Kafka engine table for clickhouse_ingestion_warnings.
#
# These tables coexist alongside the existing MSK Kafka engine table, reading from the
# same topic but via the warpstream_ingestion named collection with its own consumer
# group to avoid conflicts with the MSK table.
#
# New tables (INGESTION_SMALL, matching existing MSK table from migration 0157):
# - kafka_ingestion_warnings_ws + ingestion_warnings_ws_mv

operations = [
    run_sql_with_exceptions(
        KAFKA_INGESTION_WARNINGS_WS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        INGESTION_WARNINGS_WS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]

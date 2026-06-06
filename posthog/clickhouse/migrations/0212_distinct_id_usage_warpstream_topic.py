from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.distinct_id_usage.sql import (
    DISTINCT_ID_USAGE_MV_SQL,
    KAFKA_DISTINCT_ID_USAGE_TABLE_SQL,
    KAFKA_TABLE_NAME,
    MV_NAME,
)

# Migration to switch distinct_id_usage ingestion from the main clickhouse_events_json
# topic to the new distinct_id_usage_events_json topic populated by a WarpStream pipeline.
#
# The WarpStream pipeline extracts only the fields needed (team_id, distinct_id, created_at)
# from clickhouse_events_json and writes to the new topic, reducing the data volume
# that ClickHouse needs to process.
#
# Changes:
# - Kafka table schema simplified to only team_id, distinct_id, created_at
# - Topic changed from clickhouse_events_json to distinct_id_usage_events_json
# - MV updated to use created_at instead of timestamp

operations = [
    # 1. Drop the existing MV first (it depends on the Kafka table)
    run_sql_with_exceptions(
        f"DROP VIEW IF EXISTS {MV_NAME}",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    # 2. Drop the existing Kafka table
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {KAFKA_TABLE_NAME}",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    # 3. Create new Kafka table with simplified schema pointing to new topic
    run_sql_with_exceptions(
        KAFKA_DISTINCT_ID_USAGE_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    # 4. Create new MV using created_at instead of timestamp
    run_sql_with_exceptions(
        DISTINCT_ID_USAGE_MV_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
]

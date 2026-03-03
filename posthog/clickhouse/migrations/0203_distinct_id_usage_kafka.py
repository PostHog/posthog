from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.models.distinct_id_usage.sql import (
    DISTINCT_ID_USAGE_DATA_TABLE_SQL,
    DISTRIBUTED_DISTINCT_ID_USAGE_TABLE_SQL,
    WRITABLE_DISTINCT_ID_USAGE_TABLE_SQL,
)

# Migration to create distinct_id_usage tables with Kafka-based ingestion.
#
# This creates a sharded table that tracks distinct_id usage by aggregating
# events from the events Kafka topic using a separate consumer group.
# This approach decouples from the main events write path.
#
# Architecture:
# - sharded_distinct_id_usage: Sharded SummingMergeTree on DATA nodes
# - distinct_id_usage: Distributed read table on DATA + COORDINATOR nodes
# - writable_distinct_id_usage: Distributed write table on INGESTION_MEDIUM nodes
# - kafka_distinct_id_usage: Kafka engine table on INGESTION_MEDIUM nodes
# - distinct_id_usage_mv: Materialized view on INGESTION_MEDIUM nodes
#
# NOTE: The Kafka table and MV SQL are hardcoded here because migration 0211
# changes these to use a different topic. Migrations must be immutable.

KAFKA_EVENTS_JSON = f"{settings.KAFKA_PREFIX}clickhouse_events_json"

# Original Kafka table schema - reads from clickhouse_events_json topic
KAFKA_DISTINCT_ID_USAGE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS kafka_distinct_id_usage
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC')
) ENGINE = {engine}
SETTINGS kafka_skip_broken_messages = 100
""".format(
    engine=kafka_engine(topic=KAFKA_EVENTS_JSON, group="clickhouse_distinct_id_usage"),
)

# Original MV SQL
DISTINCT_ID_USAGE_MV_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS distinct_id_usage_mv
TO writable_distinct_id_usage
AS SELECT
    team_id,
    distinct_id,
    toStartOfMinute(timestamp) AS minute,
    1 AS event_count
FROM kafka_distinct_id_usage
"""

operations = [
    # 1. Create sharded data table on data nodes only
    run_sql_with_exceptions(
        DISTINCT_ID_USAGE_DATA_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # 2. Create distributed read table on all nodes
    run_sql_with_exceptions(
        DISTRIBUTED_DISTINCT_ID_USAGE_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    # 3. Create writable distributed table on ingestion nodes
    run_sql_with_exceptions(
        WRITABLE_DISTINCT_ID_USAGE_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    # 4. Create Kafka table on ingestion nodes
    run_sql_with_exceptions(
        KAFKA_DISTINCT_ID_USAGE_TABLE_SQL,
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    # 5. Create MV on ingestion nodes (reads from Kafka, writes to writable table)
    run_sql_with_exceptions(
        DISTINCT_ID_USAGE_MV_SQL,
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
]

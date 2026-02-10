"""SQL definitions for agent_logs tables and materialized views.

This module defines the ClickHouse tables for ingesting Twig agent logs via a dedicated
Kafka pipeline. Agent logs bypass the LogsIngestionConsumer and flow directly from
Kafka to ClickHouse, similar to distinct_id_usage and session_replay_events.

Architecture:
    Twig Agent → OTEL → capture-logs-agent → Kafka (agent_logs)
                                                   ↓
                                    kafka_agent_logs (Kafka engine)
                                                   ↓
                                    kafka_agent_logs_mv → agent_logs (dedicated table)

The team_id is extracted from Kafka headers (set by capture-logs from API token).
Task/run IDs are extracted from OTEL resource attributes for fast queries.
"""

from posthog.clickhouse.kafka_engine import kafka_engine

KAFKA_AGENT_LOGS_TOPIC = "agent_logs"
CONSUMER_GROUP_AGENT_LOGS = "clickhouse_agent_logs"

AGENT_LOGS_TABLE_NAME = "agent_logs"
KAFKA_TABLE_NAME = "kafka_agent_logs"
MV_TABLE_NAME = "kafka_agent_logs_mv"
METRICS_MV_TABLE_NAME = "kafka_agent_logs_kafka_metrics_mv"


def AGENT_LOGS_TABLE_SQL() -> str:
    """
    Dedicated agent_logs table optimized for task/run queries.

    Schema designed for Twig agent log access patterns:
    - Primary queries by team_id + task_id + run_id
    - Secondary queries by team_id + timestamp
    - event_type as dedicated column for filtering
    """
    return f"""
CREATE TABLE IF NOT EXISTS {AGENT_LOGS_TABLE_NAME}
(
    -- Identity
    `uuid` UUID DEFAULT generateUUIDv4(),
    `team_id` Int32,
    `task_id` String,
    `run_id` String,

    -- Timestamps
    `timestamp` DateTime64(6),
    `observed_timestamp` DateTime64(6),

    -- Log metadata
    `severity_text` LowCardinality(String) DEFAULT 'INFO',
    `severity_number` Int32 DEFAULT 9,
    `service_name` LowCardinality(String) DEFAULT 'twig-agent',

    -- Log content
    `body` String,
    `event_type` LowCardinality(String),

    -- Deployment environment
    `device_type` LowCardinality(String) DEFAULT 'local',

    -- Flexible attributes
    `attributes` Map(LowCardinality(String), String),
    `resource_attributes` Map(LowCardinality(String), String)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (team_id, task_id, run_id, timestamp, uuid)
TTL timestamp + INTERVAL 60 DAY
"""


def KAFKA_AGENT_LOGS_TABLE_SQL() -> str:
    """Kafka engine table consuming from agent_logs topic (Avro format from capture-logs)."""
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    `uuid` String,
    `trace_id` String,
    `span_id` String,
    `trace_flags` Int32,
    `timestamp` DateTime64(6),
    `observed_timestamp` DateTime64(6),
    `body` String,
    `severity_text` String,
    `severity_number` Int32,
    `service_name` String,
    `resource_attributes` Map(LowCardinality(String), String),
    `instrumentation_scope` String,
    `event_name` String,
    `attributes` Map(LowCardinality(String), String)
)
ENGINE = {engine}
SETTINGS kafka_skip_broken_messages = 100
""".format(
        table_name=KAFKA_TABLE_NAME,
        engine=kafka_engine(
            topic=KAFKA_AGENT_LOGS_TOPIC,
            group=CONSUMER_GROUP_AGENT_LOGS,
            serialization="Avro",
        ),
    )


def KAFKA_AGENT_LOGS_MV_SQL() -> str:
    """Materialized view: Kafka → agent_logs table with transformations"""
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} TO {target_table}
AS SELECT
    toUUID(uuid) as uuid,
    coalesce(toInt32OrNull(_headers.value[indexOf(_headers.name, 'team_id')]), toInt32OrNull(trimBoth(resource_attributes['team_id'], '"')), 0) as team_id,
    trimBoth(coalesce(resource_attributes['task_id'], ''), '"') as task_id,
    trimBoth(coalesce(resource_attributes['run_id'], ''), '"') as run_id,
    timestamp,
    observed_timestamp,
    severity_text,
    severity_number,
    trimBoth(service_name, '"') as service_name,
    body,
    trimBoth(coalesce(attributes['event_type'], event_name, ''), '"') as event_type,
    trimBoth(coalesce(resource_attributes['device_type'], 'local'), '"') as device_type,
    mapApply((k, v) -> (k, trimBoth(v, '"')), attributes) as attributes,
    mapApply((k, v) -> (k, trimBoth(v, '"')), resource_attributes) as resource_attributes
FROM {kafka_table}
SETTINGS min_insert_block_size_rows=0, min_insert_block_size_bytes=0
""".format(
        mv_name=MV_TABLE_NAME,
        target_table=AGENT_LOGS_TABLE_NAME,
        kafka_table=KAFKA_TABLE_NAME,
    )


def LOGS_KAFKA_METRICS_TABLE_SQL() -> str:
    """Shared metrics table for Kafka consumer lag monitoring.

    This table may already exist (created by the logs cluster). Using IF NOT EXISTS
    so it's safe to run in both CI (where it doesn't exist) and prod (where it does).
    """
    return """
CREATE TABLE IF NOT EXISTS logs_kafka_metrics
(
    `_partition` UInt32,
    `_topic` String,
    `max_offset` SimpleAggregateFunction(max, UInt64),
    `max_observed_timestamp` SimpleAggregateFunction(max, DateTime64(9)),
    `max_timestamp` SimpleAggregateFunction(max, DateTime64(9)),
    `max_created_at` SimpleAggregateFunction(max, DateTime64(9)),
    `max_lag` SimpleAggregateFunction(max, UInt64)
)
ENGINE = MergeTree
ORDER BY (_topic, _partition)
"""


def KAFKA_AGENT_LOGS_METRICS_MV_SQL() -> str:
    """Materialized view for monitoring agent_logs Kafka consumer lag."""
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} TO logs_kafka_metrics
AS SELECT
    _partition,
    _topic,
    maxSimpleState(_offset) as max_offset,
    maxSimpleState(observed_timestamp) as max_observed_timestamp,
    maxSimpleState(timestamp) as max_timestamp,
    maxSimpleState(now64(9)) as max_created_at,
    maxSimpleState(now64(9) - observed_timestamp) as max_lag
FROM {kafka_table}
GROUP BY _partition, _topic
""".format(
        mv_name=METRICS_MV_TABLE_NAME,
        kafka_table=KAFKA_TABLE_NAME,
    )

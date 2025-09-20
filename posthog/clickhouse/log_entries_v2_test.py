from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS, kafka_engine, ttl_period
from posthog.clickhouse.table_engines import ReplacingMergeTree
from posthog.kafka_client.topics import KAFKA_LOG_ENTRIES_V2_TEST
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

# NOTE: This module contains tables that are temporary and used for testing Mr Blobby V2.
# They will be removed once Mr Blobby V2 is fully deployed.

LOG_ENTRIES_V2_TABLE = "log_entries_v2_test"
LOG_ENTRIES_V2_TTL_DAYS = 90

LOG_ENTRIES_V2_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause} (
    team_id UInt64,
    -- The name of the service or product that generated the logs.
    -- Examples: batch_exports
    log_source LowCardinality(String),
    -- An id for the log source.
    -- Set log_source to avoid collision with ids from other log sources if the id generation is not safe.
    -- Examples: A batch export id, a cronjob id, a plugin id.
    log_source_id String,
    -- A secondary id e.g. for the instance of log_source that generated this log.
    -- This may be ommitted if log_source is a singleton.
    -- Examples: A batch export run id, a plugin_config id, a thread id, a process id, a machine id.
    instance_id String,
    -- Timestamp indicating when the log was generated.
    timestamp DateTime64(6, 'UTC'),
    -- The log level.
    -- Examples: INFO, WARNING, DEBUG, ERROR.
    level LowCardinality(String),
    -- The actual log message.
    message String
    {extra_fields}
) ENGINE = {engine}
"""


def LOG_ENTRIES_V2_TABLE_ENGINE():
    return ReplacingMergeTree(LOG_ENTRIES_V2_TABLE, ver="_timestamp")


def LOG_ENTRIES_V2_TABLE_SQL(on_cluster=True):
    return (
        LOG_ENTRIES_V2_TABLE_BASE_SQL
        + """ PARTITION BY toStartOfHour(timestamp) ORDER BY (team_id, log_source, log_source_id, instance_id, timestamp)
              {ttl_period}
              SETTINGS index_granularity=512
          """
    ).format(
        table_name=LOG_ENTRIES_V2_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        extra_fields=KAFKA_COLUMNS,
        engine=LOG_ENTRIES_V2_TABLE_ENGINE(),
        ttl_period=ttl_period("timestamp", LOG_ENTRIES_V2_TTL_DAYS, unit="DAY"),
    )


def KAFKA_LOG_ENTRIES_V2_TABLE_SQL(on_cluster=True):
    return LOG_ENTRIES_V2_TABLE_BASE_SQL.format(
        table_name="kafka_" + LOG_ENTRIES_V2_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(topic=KAFKA_LOG_ENTRIES_V2_TEST),
        extra_fields="",
    )


def LOG_ENTRIES_V2_TABLE_MV_SQL(on_cluster=True):
    return """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {table_name}_mv
      ON CLUSTER '{cluster}'
      TO {database}.{table_name}
      AS SELECT
          team_id,
          log_source,
          log_source_id,
          instance_id,
          timestamp,
          level,
          message,
          _timestamp,
          _offset
        FROM {database}.kafka_{table_name}
    """.format(
        table_name=LOG_ENTRIES_V2_TABLE,
        cluster=CLICKHOUSE_CLUSTER,
        database=CLICKHOUSE_DATABASE,
    )


INSERT_LOG_ENTRY_V2_SQL = f"""
  INSERT INTO {LOG_ENTRIES_V2_TABLE}
  SELECT
    %(team_id)s,
    %(log_source)s,
    %(log_source_id)s,
    %(instance_id)s,
    %(timestamp)s,
    %(level)s,
    %(message)s,
    now(),
    0
"""

TRUNCATE_LOG_ENTRIES_V2_TABLE_SQL = f"""
    TRUNCATE TABLE IF EXISTS {LOG_ENTRIES_V2_TABLE} {ON_CLUSTER_CLAUSE()}
"""

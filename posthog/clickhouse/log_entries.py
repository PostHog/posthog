from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS, kafka_engine, ttl_period
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_LOG_ENTRIES
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

LOG_ENTRIES_TABLE = "log_entries"
LOG_ENTRIES_DISTRIBUTED_TABLE = "distributed_log_entries"
LOG_ENTRIES_WRITABLE_TABLE = "writable_log_entries"
LOG_ENTRIES_SHARDED_TABLE = "sharded_log_entries"
LOG_ENTRIES_TTL_DAYS = 90


LOG_ENTRIES_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
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


def LOG_ENTRIES_TABLE_ENGINE(table_name: str, replication_scheme=ReplicationScheme.REPLICATED):
    return ReplacingMergeTree(table_name, ver="_timestamp", replication_scheme=replication_scheme)


def LOG_ENTRIES_TABLE_SQL(on_cluster=True):
    return (
        LOG_ENTRIES_TABLE_BASE_SQL
        + """PARTITION BY toStartOfHour(timestamp) ORDER BY (team_id, log_source, log_source_id, instance_id, timestamp)
{ttl_period}
SETTINGS index_granularity=512
"""
    ).format(
        table_name=LOG_ENTRIES_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        extra_fields=KAFKA_COLUMNS,
        engine=LOG_ENTRIES_TABLE_ENGINE(LOG_ENTRIES_TABLE),
        ttl_period=ttl_period("timestamp", LOG_ENTRIES_TTL_DAYS, unit="DAY"),
    )


def KAFKA_LOG_ENTRIES_TABLE_SQL(on_cluster=True):
    return LOG_ENTRIES_TABLE_BASE_SQL.format(
        table_name="kafka_" + LOG_ENTRIES_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(topic=KAFKA_LOG_ENTRIES),
        extra_fields="",
    )


LOG_ENTRIES_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS {table_name}_mv ON CLUSTER '{cluster}'
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
    table_name=LOG_ENTRIES_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    database=CLICKHOUSE_DATABASE,
)


INSERT_LOG_ENTRY_SQL = """
INSERT INTO log_entries SELECT %(team_id)s, %(log_source)s, %(log_source_id)s, %(instance_id)s, %(timestamp)s, %(level)s, %(message)s, now(), 0
"""

TRUNCATE_LOG_ENTRIES_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {LOG_ENTRIES_SHARDED_TABLE} {ON_CLUSTER_CLAUSE()}"

# Log entries rework

DROP_KAFKA_LOG_ENTRIES_V3_TABLE_SQL = f"DROP TABLE IF EXISTS kafka_{LOG_ENTRIES_TABLE}_v3"
DROP_LOG_ENTRIES_TABLE_MV_SQL = f"DROP TABLE IF EXISTS {LOG_ENTRIES_TABLE}_v3_mv"


def LOG_ENTRIES_SHARDED_TABLE_SQL():
    return (
        LOG_ENTRIES_TABLE_BASE_SQL
        + """PARTITION BY toYYYYMMDD(timestamp) ORDER BY (team_id, log_source, log_source_id, instance_id, timestamp)
{ttl_period}
SETTINGS index_granularity=1024, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=LOG_ENTRIES_SHARDED_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        extra_fields=KAFKA_COLUMNS,
        engine=LOG_ENTRIES_TABLE_ENGINE(LOG_ENTRIES_SHARDED_TABLE, replication_scheme=ReplicationScheme.SHARDED),
        ttl_period=ttl_period("timestamp", LOG_ENTRIES_TTL_DAYS, unit="DAY"),
    )


def LOG_ENTRIES_DISTRIBUTED_TABLE_SQL():
    return (LOG_ENTRIES_TABLE_BASE_SQL).format(
        table_name=LOG_ENTRIES_DISTRIBUTED_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        extra_fields=KAFKA_COLUMNS,
        engine=Distributed(data_table=LOG_ENTRIES_SHARDED_TABLE, cluster=CLICKHOUSE_CLUSTER, sharding_key="rand()"),
    )


def LOG_ENTRIES_WRITABLE_TABLE_SQL():
    return (LOG_ENTRIES_TABLE_BASE_SQL).format(
        table_name=LOG_ENTRIES_WRITABLE_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        extra_fields=KAFKA_COLUMNS,
        engine=Distributed(data_table=LOG_ENTRIES_SHARDED_TABLE, cluster=CLICKHOUSE_CLUSTER, sharding_key="rand()"),
    )


def KAFKA_LOG_ENTRIES_V3_TABLE_SQL():
    return (
        LOG_ENTRIES_TABLE_BASE_SQL
        + """
    SETTINGS kafka_skip_broken_messages = 100
    """
    ).format(
        table_name=f"kafka_{LOG_ENTRIES_TABLE}_v3",
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=kafka_engine(topic=KAFKA_LOG_ENTRIES, group="clickhouse_log_entries"),
        extra_fields="",
    )


def LOG_ENTRIES_V3_TABLE_MV_SQL():
    return """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {table_name}_v3_mv
    TO {database}.{to_table}
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
    FROM {database}.{from_table}
    WHERE toDate(timestamp) <= today()
    """.format(
        table_name=LOG_ENTRIES_TABLE,
        to_table=LOG_ENTRIES_WRITABLE_TABLE,
        from_table=f"kafka_{LOG_ENTRIES_TABLE}_v3",
        database=CLICKHOUSE_DATABASE,
    )

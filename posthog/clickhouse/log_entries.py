from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_LOG_ENTRIES,
    CONSUMER_GROUP_LOG_ENTRIES_WS,
    KAFKA_COLUMNS,
    kafka_engine,
    ttl_period,
)
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_LOG_ENTRIES
from posthog.settings import (
    CLICKHOUSE_CLUSTER,
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
)

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


def KAFKA_LOG_ENTRIES_TABLE_SQL(on_cluster=True, group: str = "group1"):
    return LOG_ENTRIES_TABLE_BASE_SQL.format(
        table_name="kafka_" + LOG_ENTRIES_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(topic=KAFKA_LOG_ENTRIES, group=group),
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

# WarpStream Kafka engine tables (coexist alongside MSK tables, same target)

KAFKA_LOG_ENTRIES_WS_TABLE_NAME = f"kafka_{LOG_ENTRIES_TABLE}_ws"
LOG_ENTRIES_WS_MV_NAME = f"{LOG_ENTRIES_TABLE}_ws_mv"

DROP_KAFKA_LOG_ENTRIES_WS_TABLE_SQL = f"DROP TABLE IF EXISTS {KAFKA_LOG_ENTRIES_WS_TABLE_NAME}"
DROP_LOG_ENTRIES_WS_MV_SQL = f"DROP TABLE IF EXISTS {LOG_ENTRIES_WS_MV_NAME}"


def KAFKA_LOG_ENTRIES_WS_TABLE_SQL():
    return (
        LOG_ENTRIES_TABLE_BASE_SQL
        + """
    SETTINGS kafka_skip_broken_messages = 100
    """
    ).format(
        table_name=KAFKA_LOG_ENTRIES_WS_TABLE_NAME,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=kafka_engine(
            topic=KAFKA_LOG_ENTRIES,
            group=CONSUMER_GROUP_LOG_ENTRIES_WS,
            named_collection=CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        ),
        extra_fields="",
    )


def LOG_ENTRIES_WS_MV_SQL():
    return """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
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
        mv_name=LOG_ENTRIES_WS_MV_NAME,
        to_table=LOG_ENTRIES_WRITABLE_TABLE,
        from_table=KAFKA_LOG_ENTRIES_WS_TABLE_NAME,
        database=CLICKHOUSE_DATABASE,
    )


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
        engine=kafka_engine(topic=KAFKA_LOG_ENTRIES, group=CONSUMER_GROUP_LOG_ENTRIES),
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


# log_entries on the aux cluster (S3-tiered)
#
# `log_entries_data` on the aux cluster stores log_entries: hot days on local disk, days older
# than LOG_ENTRIES_AUX_HOT_DAYS on the `cold` (S3) volume, 90 day delete. A dedicated Kafka
# consumer (kafka_log_entries_aux + log_entries_aux_mv -> writable_log_entries_aux) feeds it.
# `log_entries` is the reader over this data on the aux and data nodes. On the data nodes,
# `log_entries_distributed` reads `sharded_log_entries` and is the rollback target for reads.
# On the aux nodes, `log_entries_distributed` is a second name for the aux reader.
#
# The S3 storage policy only exists on deployed cloud clusters, so the tiering clauses are
# resolved per run mode and omitted locally.

LOG_ENTRIES_DATA_TABLE = "log_entries_data"
LOG_ENTRIES_AUX_DISTRIBUTED_TABLE = "log_entries_distributed"
LOG_ENTRIES_AUX_WRITABLE_TABLE = "writable_log_entries_aux"
KAFKA_LOG_ENTRIES_AUX_TABLE = "kafka_log_entries_aux"
LOG_ENTRIES_AUX_MV = "log_entries_aux_mv"
LOG_ENTRIES_AUX_HOT_DAYS = 7


def _log_entries_data_ttl() -> str:
    from posthog.run_mode import run_mode

    if run_mode().is_deployed_cloud:
        return (
            f"TTL toDate(timestamp) + INTERVAL {LOG_ENTRIES_AUX_HOT_DAYS} DAY TO VOLUME 'cold', "
            f"toDate(timestamp) + INTERVAL {LOG_ENTRIES_TTL_DAYS} DAY DELETE"
        )
    return f"TTL toDate(timestamp) + INTERVAL {LOG_ENTRIES_TTL_DAYS} DAY DELETE"


def _log_entries_data_settings() -> str:
    from posthog.run_mode import run_mode

    base = "index_granularity = 1024, ttl_only_drop_parts = 1"
    if run_mode().is_deployed_cloud:
        return base + ", storage_policy = 's3_tiered'"
    return base


def LOG_ENTRIES_DATA_TABLE_SQL():
    return (
        LOG_ENTRIES_TABLE_BASE_SQL
        + """PARTITION BY toYYYYMMDD(timestamp) ORDER BY (team_id, log_source, log_source_id, instance_id, timestamp)
{ttl_period}
SETTINGS {table_settings}
"""
    ).format(
        table_name=LOG_ENTRIES_DATA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        extra_fields=KAFKA_COLUMNS,
        engine=LOG_ENTRIES_TABLE_ENGINE(LOG_ENTRIES_DATA_TABLE),
        ttl_period=_log_entries_data_ttl(),
        table_settings=_log_entries_data_settings(),
    )


def _log_entries_aux_distributed_engine():
    from django.conf import settings

    return Distributed(data_table=LOG_ENTRIES_DATA_TABLE, cluster=settings.CLICKHOUSE_AUX_CLUSTER)


def LOG_ENTRIES_AUX_DISTRIBUTED_TABLE_SQL():
    return LOG_ENTRIES_TABLE_BASE_SQL.format(
        table_name=LOG_ENTRIES_AUX_DISTRIBUTED_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        extra_fields=KAFKA_COLUMNS,
        engine=_log_entries_aux_distributed_engine(),
    )


def LOG_ENTRIES_AUX_READER_SQL():
    """The app-facing `log_entries` name as the aux-cluster reader over `log_entries_data`.

    On the data nodes of deployed cloud regions, the name comes from an operational
    EXCHANGE with `log_entries_distributed`, which keeps the main-cluster reader as the
    rollback target. This SQL creates the same table on the aux nodes and in fresh
    environments.
    """
    return LOG_ENTRIES_TABLE_BASE_SQL.format(
        table_name=LOG_ENTRIES_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        extra_fields=KAFKA_COLUMNS,
        engine=_log_entries_aux_distributed_engine(),
    )


def _as_create_or_replace(sql: str) -> str:
    assert "CREATE TABLE IF NOT EXISTS" in sql
    return sql.replace("CREATE TABLE IF NOT EXISTS", "CREATE OR REPLACE TABLE", 1)


def LOG_ENTRIES_DATA_NODE_READERS_SQL() -> list[str]:
    """The data-node read layout: `log_entries` reads aux, `log_entries_distributed` reads main.

    Both are Distributed tables that hold no data, so `CREATE OR REPLACE` declares the
    target state directly. A second run, or a run on a node that already has this layout,
    changes nothing. An EXCHANGE of the two names would swap them back on a second run.
    """
    return [
        _as_create_or_replace(LOG_ENTRIES_AUX_READER_SQL()),
        _as_create_or_replace(
            LOG_ENTRIES_TABLE_BASE_SQL.format(
                table_name=LOG_ENTRIES_AUX_DISTRIBUTED_TABLE,
                on_cluster_clause=ON_CLUSTER_CLAUSE(False),
                extra_fields=KAFKA_COLUMNS,
                engine=Distributed(
                    data_table=LOG_ENTRIES_SHARDED_TABLE, cluster=CLICKHOUSE_CLUSTER, sharding_key="rand()"
                ),
            )
        ),
    ]


def LOG_ENTRIES_AUX_WRITABLE_TABLE_SQL():
    return LOG_ENTRIES_TABLE_BASE_SQL.format(
        table_name=LOG_ENTRIES_AUX_WRITABLE_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        extra_fields=KAFKA_COLUMNS,
        engine=_log_entries_aux_distributed_engine(),
    )


def KAFKA_LOG_ENTRIES_AUX_TABLE_SQL():
    from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_LOG_ENTRIES_AUX, kafka_num_consumers

    return (
        LOG_ENTRIES_TABLE_BASE_SQL
        + """
    SETTINGS kafka_skip_broken_messages = 100,
             kafka_num_consumers = {num_consumers},
             kafka_thread_per_consumer = 1,
             kafka_poll_timeout_ms = 10000,
             kafka_max_block_size = 100000
    """
    ).format(
        num_consumers=kafka_num_consumers(1),
        table_name=KAFKA_LOG_ENTRIES_AUX_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=kafka_engine(
            topic=KAFKA_LOG_ENTRIES,
            group=CONSUMER_GROUP_LOG_ENTRIES_AUX,
            named_collection=CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        ),
        extra_fields="",
    )


def LOG_ENTRIES_AUX_MV_SQL():
    return """
    CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
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
        mv_name=LOG_ENTRIES_AUX_MV,
        to_table=LOG_ENTRIES_AUX_WRITABLE_TABLE,
        from_table=KAFKA_LOG_ENTRIES_AUX_TABLE,
        database=CLICKHOUSE_DATABASE,
    )

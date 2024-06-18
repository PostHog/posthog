from django.conf import settings

from posthog.clickhouse.kafka_engine import kafka_engine, ttl_period
from posthog.clickhouse.table_engines import (
    Distributed,
    ReplicationScheme,
    MergeTreeEngine,
)
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_NETWORKS_VITALS_EVENTS

NETWORK_VITALS_DATA_TABLE = lambda: "sharded_network_vitals"


KAFKA_NETWORK_VITALS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    session_id VARCHAR,
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    current_url VARCHAR,
    fcp Nullable(Float64),
    lcp Nullable(Float64),
    cls Nullable(Float64),
    inp Nullable(Float64),
    -- we store the rest of the properties as a JSON string, just like the events table
    properties VARCHAR CODEC(ZSTD(3)),
) ENGINE = {engine}
"""

NETWORK_VITALS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    session_id VARCHAR,
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    current_url VARCHAR,
    fcp Nullable(Float64),
    lcp Nullable(Float64),
    cls Nullable(Float64),
    inp Nullable(Float64),
    properties VARCHAR CODEC(ZSTD(3)),
    _timestamp DateTime,
    _offset UInt64,
    _partition UInt64
) ENGINE = {engine}
"""

NETWORK_VITALS_DATA_TABLE_ENGINE = lambda: MergeTreeEngine(
    "network_vitals", replication_scheme=ReplicationScheme.SHARDED
)

NETWORK_VITALS_TABLE_SQL = lambda: (
    NETWORK_VITALS_TABLE_BASE_SQL
    + """
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (team_id,  toDate(timestamp), current_url)
    {ttl_period}
"""
).format(
    table_name=NETWORK_VITALS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=NETWORK_VITALS_DATA_TABLE_ENGINE(),
    ttl_period=ttl_period("timestamp", 1, unit="YEAR"),
)

KAFKA_NETWORK_VITALS_TABLE_SQL = lambda: KAFKA_NETWORK_VITALS_TABLE_BASE_SQL.format(
    table_name="kafka_network_vitals",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_CLICKHOUSE_NETWORKS_VITALS_EVENTS),
)

NETWORK_VITALS_TABLE_MV_SQL = (
    lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS network_vitals_mv ON CLUSTER '{cluster}'
TO {database}.{target_table}
AS SELECT
    session_id,
    team_id,
    timestamp,
    current_url,
    fcp,
    lcp,
    cls,
    inp,
    properties,
    _timestamp,
    _offset,
    _partition
FROM {database}.kafka_network_vitals
""".format(
        target_table="writable_network_vitals",
        cluster=settings.CLICKHOUSE_CLUSTER,
        database=settings.CLICKHOUSE_DATABASE,
    )
)

# Distributed engine tables are only created if CLICKHOUSE_REPLICATED

# This table is responsible for writing to sharded_heatmaps based on a sharding key.
WRITABLE_NETWORK_VITALS_TABLE_SQL = lambda: NETWORK_VITALS_TABLE_BASE_SQL.format(
    table_name="writable_network_vitals",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(
        data_table=NETWORK_VITALS_DATA_TABLE(),
        # we'll most often query by current url, so we'll use that in the sharding key
        sharding_key="cityHash64(concat(toString(team_id), '-', current_url, '-', toString(toDate(timestamp))))",
    ),
)

# This table is responsible for reading from heatmaps on a cluster setting
DISTRIBUTED_NETWORK_VITALS_TABLE_SQL = lambda: NETWORK_VITALS_TABLE_BASE_SQL.format(
    table_name="network_vitals",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(
        data_table=NETWORK_VITALS_DATA_TABLE(),
        # we'll most often query by current url, so we'll use that in the sharding key
        sharding_key="cityHash64(concat(toString(team_id), '-', current_url, '-', toString(toDate(timestamp))))",
    ),
)

DROP_NETWORK_VITALS_TABLE_SQL = lambda: (
    f"DROP TABLE IF EXISTS {NETWORK_VITALS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
)

TRUNCATE_NETWORK_VITALS_TABLE_SQL = lambda: (
    f"TRUNCATE TABLE IF EXISTS {NETWORK_VITALS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
)

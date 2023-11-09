from django.conf import settings

from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, kafka_engine
from posthog.clickhouse.table_engines import (
    Distributed,
    MergeTreeEngine,
    ReplicationScheme,
)
from posthog.kafka_client.topics import KAFKA_INGESTION_WARNINGS

INGESTION_WARNINGS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    team_id Int64,
    source LowCardinality(VARCHAR),
    type VARCHAR,
    details VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC')
    {extra_fields}
) ENGINE = {engine}
"""

INGESTION_WARNINGS_DATA_TABLE_ENGINE = lambda: MergeTreeEngine(
    "sharded_ingestion_warnings", replication_scheme=ReplicationScheme.SHARDED
)

INGESTION_WARNINGS_DATA_TABLE_SQL = lambda: (
    INGESTION_WARNINGS_TABLE_BASE_SQL
    + """PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (team_id, toHour(timestamp), type, source, timestamp)
"""
).format(
    table_name="sharded_ingestion_warnings",
    cluster=settings.CLICKHOUSE_CLUSTER,
    extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
    engine=INGESTION_WARNINGS_DATA_TABLE_ENGINE(),
)

KAFKA_INGESTION_WARNINGS_TABLE_SQL = lambda: INGESTION_WARNINGS_TABLE_BASE_SQL.format(
    table_name="kafka_ingestion_warnings",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_INGESTION_WARNINGS),
    materialized_columns="",
    extra_fields="",
)

INGESTION_WARNINGS_MV_TABLE_SQL = (
    lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS ingestion_warnings_mv ON CLUSTER '{cluster}'
TO {database}.{target_table}
AS SELECT
team_id,
source,
type,
details,
timestamp,
_timestamp,
_offset,
_partition
FROM {database}.kafka_ingestion_warnings
""".format(
        target_table="ingestion_warnings",
        cluster=settings.CLICKHOUSE_CLUSTER,
        database=settings.CLICKHOUSE_DATABASE,
    )
)

# This table is responsible for writing to sharded_ingestion_warnings based on a sharding key.
DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL = lambda: INGESTION_WARNINGS_TABLE_BASE_SQL.format(
    table_name="ingestion_warnings",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table="sharded_ingestion_warnings", sharding_key="rand()"),
    extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
    materialized_columns="",
)


INSERT_INGESTION_WARNING = f"""
INSERT INTO sharded_ingestion_warnings (team_id, source, type, details, timestamp, _timestamp, _offset, _partition)
SELECT %(team_id)s, %(source)s, %(type)s, %(details)s, %(timestamp)s, now(), 0, 0
"""

from django.conf import settings

from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, kafka_engine
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_INGESTION_WARNINGS

DROP_INGESTION_WARNINGS_TABLE_MV_SQL = f"DROP TABLE IF EXISTS ingestion_warnings_mv"
DROP_KAFKA_INGESTION_WARNINGS_TABLE_SQL = f"DROP TABLE IF EXISTS kafka_ingestion_warnings"


def INGESTION_WARNINGS_TABLE_BASE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    source LowCardinality(VARCHAR),
    type VARCHAR,
    details VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC')
    {extra_fields}
) ENGINE = {engine}
"""


def INGESTION_WARNINGS_DATA_TABLE_ENGINE():
    return MergeTreeEngine("sharded_ingestion_warnings", replication_scheme=ReplicationScheme.SHARDED)


def INGESTION_WARNINGS_DATA_TABLE_SQL():
    return (
        INGESTION_WARNINGS_TABLE_BASE_SQL()
        + """PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (team_id, toHour(timestamp), type, source, timestamp)
"""
    ).format(
        table_name="sharded_ingestion_warnings",
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
        engine=INGESTION_WARNINGS_DATA_TABLE_ENGINE(),
    )


def KAFKA_INGESTION_WARNINGS_TABLE_SQL():
    return INGESTION_WARNINGS_TABLE_BASE_SQL().format(
        table_name="kafka_ingestion_warnings",
        engine=kafka_engine(topic=KAFKA_INGESTION_WARNINGS),
        materialized_columns="",
        extra_fields="",
    )


def INGESTION_WARNINGS_MV_TABLE_SQL(target_table="writable_ingestion_warnings"):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS ingestion_warnings_mv
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
        target_table=target_table,
        database=settings.CLICKHOUSE_DATABASE,
    )


# This table is responsible for writing to sharded_ingestion_warnings based on a sharding key.


def DISTRIBUTED_INGESTION_WARNINGS_TABLE_SQL():
    return INGESTION_WARNINGS_TABLE_BASE_SQL().format(
        table_name="ingestion_warnings",
        engine=Distributed(data_table="sharded_ingestion_warnings", sharding_key="rand()"),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
        materialized_columns="",
    )


def WRITABLE_INGESTION_WARNINGS_TABLE_SQL():
    return INGESTION_WARNINGS_TABLE_BASE_SQL().format(
        table_name="writable_ingestion_warnings",
        engine=Distributed(data_table="sharded_ingestion_warnings", sharding_key="rand()"),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
        materialized_columns="",
    )


INSERT_INGESTION_WARNING = f"""
INSERT INTO sharded_ingestion_warnings (team_id, source, type, details, timestamp, _timestamp, _offset, _partition)
SELECT %(team_id)s, %(source)s, %(type)s, %(details)s, %(timestamp)s, now(), 0, 0
"""

from django.conf import settings

from posthog.clickhouse.kafka_engine import ttl_period
from posthog.clickhouse.table_engines import Distributed, ReplicationScheme, SummingMergeTree

DISTINCT_ID_USAGE_TTL_DAYS = 7

TABLE_BASE_NAME = "distinct_id_usage"
WRITABLE_TABLE_NAME = f"writable_{TABLE_BASE_NAME}"
MV_NAME = f"{TABLE_BASE_NAME}_mv"


def DISTINCT_ID_USAGE_DATA_TABLE_ENGINE():
    return SummingMergeTree(
        TABLE_BASE_NAME,
        replication_scheme=ReplicationScheme.REPLICATED,
        columns="(event_count)",
    )


DISTINCT_ID_USAGE_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    distinct_id String,
    minute DateTime,
    event_count UInt64
) ENGINE = {engine}
"""


def DISTINCT_ID_USAGE_DATA_TABLE_SQL():
    return (
        DISTINCT_ID_USAGE_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(minute)
ORDER BY (team_id, minute, distinct_id)
{ttl}
"""
    ).format(
        table_name=TABLE_BASE_NAME,
        engine=DISTINCT_ID_USAGE_DATA_TABLE_ENGINE(),
        ttl=ttl_period("minute", DISTINCT_ID_USAGE_TTL_DAYS, unit="DAY"),
    )


def WRITABLE_DISTINCT_ID_USAGE_TABLE_SQL():
    return DISTINCT_ID_USAGE_TABLE_BASE_SQL.format(
        table_name=WRITABLE_TABLE_NAME,
        engine=Distributed(
            data_table=TABLE_BASE_NAME,
            cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER,
        ),
    )


def DISTINCT_ID_USAGE_MV_SQL(target_table: str = WRITABLE_TABLE_NAME):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
TO {database}.{target_table}
AS SELECT
    team_id,
    distinct_id,
    toStartOfMinute(timestamp) AS minute,
    1 AS event_count
FROM {database}.sharded_events
WHERE timestamp >= now() - INTERVAL {ttl_days} DAY
""".format(
        mv_name=MV_NAME,
        target_table=target_table,
        database=settings.CLICKHOUSE_DATABASE,
        ttl_days=DISTINCT_ID_USAGE_TTL_DAYS,
    )


def DROP_DISTINCT_ID_USAGE_DATA_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {TABLE_BASE_NAME} SYNC"


def DROP_WRITABLE_DISTINCT_ID_USAGE_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {WRITABLE_TABLE_NAME}"


def DROP_DISTINCT_ID_USAGE_MV_SQL():
    return f"DROP TABLE IF EXISTS {MV_NAME}"


def TRUNCATE_DISTINCT_ID_USAGE_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {TABLE_BASE_NAME}"

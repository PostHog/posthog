from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_NAME = "web_bots_preaggregated"

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,
    time_window_start DateTime64(6, 'UTC'),
    bot_name String,
    category String,
    host Nullable(String),
    pathname Nullable(String),
    requests UInt64,
    last_seen DateTime64(6, 'UTC'),
    computed_at DateTime64(6, 'UTC') DEFAULT now(),
    expires_at DateTime64(6, 'UTC')
) ENGINE = {engine}
"""


def SHARDED_WEB_BOTS_PREAGGREGATED_TABLE_SQL() -> str:
    return (
        TABLE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (
    team_id,
    job_id,
    time_window_start,
    bot_name,
    category,
    isNull(host),
    ifNull(host, ''),
    isNull(pathname),
    ifNull(pathname, '')
)
TTL toDateTime(expires_at)
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=f"sharded_{TABLE_NAME}",
        engine=ReplacingMergeTree(TABLE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at"),
    )


def DISTRIBUTED_WEB_BOTS_PREAGGREGATED_TABLE_SQL() -> str:
    return TABLE_SQL.format(
        table_name=TABLE_NAME,
        engine=Distributed(
            data_table=f"sharded_{TABLE_NAME}",
            sharding_key="sipHash64(job_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )

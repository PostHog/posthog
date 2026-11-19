from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "series_values_preaggregated"


def DISTRIBUTED_SERIES_VALUES_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME


def SHARDED_SERIES_VALUES_PREAGGREGATED_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_SERIES_VALUES_PREAGGREGATED_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


SERIES_VALUES_PREAGGREGATED_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,
    time_window_start DateTime64(6, 'UTC'),
    series_key String,
    value Float64,
    computed_at DateTime64(6, 'UTC') DEFAULT now(),
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_SERIES_VALUES_PREAGGREGATED_TABLE_SQL():
    return (
        SERIES_VALUES_PREAGGREGATED_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, series_key, time_window_start)
TTL toDateTime(expires_at)
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_SERIES_VALUES_PREAGGREGATED_TABLE(),
        engine=SHARDED_SERIES_VALUES_PREAGGREGATED_TABLE_ENGINE(),
    )


def DISTRIBUTED_SERIES_VALUES_PREAGGREGATED_TABLE_SQL():
    return SERIES_VALUES_PREAGGREGATED_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_SERIES_VALUES_PREAGGREGATED_TABLE(),
        engine=Distributed(
            data_table=SHARDED_SERIES_VALUES_PREAGGREGATED_TABLE(),
            sharding_key="sipHash64(job_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )

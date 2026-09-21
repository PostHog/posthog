from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

TABLE = "hourly_uniq_preaggregated"
SHARDED_TABLE = "sharded_hourly_uniq_preaggregated"

_BASE = """CREATE TABLE IF NOT EXISTS {table} (
    team_id Int64,
    job_id UUID,
    time_window_start DateTime64(6, 'UTC'),
    metric_index UInt16,
    uniq_state AggregateFunction(uniq, UUID),
    expires_at DateTime64(6, 'UTC')
) ENGINE = {engine}"""


def SHARDED_HOURLY_UNIQ_TABLE_SQL():
    return (
        _BASE.format(
            table=SHARDED_TABLE, engine=AggregatingMergeTree(TABLE, replication_scheme=ReplicationScheme.SHARDED)
        )
        + """
PARTITION BY toYYYYMM(time_window_start)
ORDER BY (team_id, job_id, time_window_start, metric_index)
TTL expires_at
SETTINGS index_granularity=8192
"""
    ).rstrip()


def HOURLY_UNIQ_TABLE_SQL():
    return _BASE.format(table=TABLE, engine=Distributed(data_table=SHARDED_TABLE, sharding_key="sipHash64(job_id)"))

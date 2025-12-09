from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

TABLE_BASE_NAME = "preaggregation_results"


def DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE():
    return TABLE_BASE_NAME


def SHARDED_PREAGGREGATION_RESULTS_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def WRITABLE_PREAGGREGATION_RESULTS_TABLE():
    return f"writable_{TABLE_BASE_NAME}"


def SHARDED_PREAGGREGATION_RESULTS_TABLE_ENGINE():
    return AggregatingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED)


PREAGGREGATION_RESULTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,
    time_window_start DateTime64(6, 'UTC'),

    -- Breakdown dimension (empty array for no breakdown)
    breakdown_value Array(String),

    -- Aggregate state column (uniqExact for precision)
    uniq_exact_state AggregateFunction(uniqExact, UUID)
) ENGINE = {engine}
"""


def SHARDED_PREAGGREGATION_RESULTS_TABLE_SQL():
    return (
        PREAGGREGATION_RESULTS_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMM(time_window_start)
ORDER BY (team_id, job_id, time_window_start, breakdown_value)
SETTINGS index_granularity=8192
"""
    ).format(
        table_name=SHARDED_PREAGGREGATION_RESULTS_TABLE(),
        engine=SHARDED_PREAGGREGATION_RESULTS_TABLE_ENGINE(),
    )


def WRITABLE_PREAGGREGATION_RESULTS_TABLE_SQL():
    return PREAGGREGATION_RESULTS_TABLE_BASE_SQL.format(
        table_name=WRITABLE_PREAGGREGATION_RESULTS_TABLE(),
        engine=Distributed(
            data_table=SHARDED_PREAGGREGATION_RESULTS_TABLE(),
            sharding_key="sipHash64(job_id)",
        ),
    )


def DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE_SQL():
    return PREAGGREGATION_RESULTS_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE(),
        engine=Distributed(
            data_table=SHARDED_PREAGGREGATION_RESULTS_TABLE(),
            sharding_key="sipHash64(job_id)",
        ),
    )


def DROP_PREAGGREGATION_RESULTS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()}"


def DROP_WRITABLE_PREAGGREGATION_RESULTS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {WRITABLE_PREAGGREGATION_RESULTS_TABLE()}"


def DROP_SHARDED_PREAGGREGATION_RESULTS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_PREAGGREGATION_RESULTS_TABLE()} SYNC"


def TRUNCATE_PREAGGREGATION_RESULTS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_PREAGGREGATION_RESULTS_TABLE()}"

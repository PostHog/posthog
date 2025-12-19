# These tables are used to save and re-use intermediate results from queries

# They are hidden behind a flag that is only visible behind a HogQLQueryModifier that is only settable in the query debugger

# One unsolved problem so far is ensuring that we can read our own writes, as often we write to this table immediately before we want to re-read the results.
# Some ideas for how to solve this in a future version:
# * write to the sharded tables rather than the distributed tables, with more control over which node run both the preagg and combiner query
# * try various clickhouse settings like select_sequential_consistency, insert_quorum_parallel, insert_quorum

# Given that this is not accessible by real customers, we can merge this before we solve this issue, and we can experiment with settings later

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

TABLE_BASE_NAME = "preaggregation_results"


def DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE():
    return TABLE_BASE_NAME


def SHARDED_PREAGGREGATION_RESULTS_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_PREAGGREGATION_RESULTS_TABLE_ENGINE():
    return AggregatingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED)


PREAGGREGATION_RESULTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,
    time_window_start DateTime64(6, 'UTC'),

    -- TTL: rows are automatically deleted during parts merges after expires_at, prefer not to use the default and set this directly
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY

    -- Breakdown dimension (empty array for no breakdown)
    breakdown_value Array(String),

    -- Aggregate state column (uniqExact for compat with queries that use count(DISTINCT person_id))
    uniq_exact_state AggregateFunction(uniqExact, UUID)
) ENGINE = {engine}
"""


def SHARDED_PREAGGREGATION_RESULTS_TABLE_SQL():
    return (
        PREAGGREGATION_RESULTS_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMM(time_window_start)
ORDER BY (team_id, job_id, time_window_start, breakdown_value)
TTL expires_at
SETTINGS index_granularity=8192
"""
    ).format(
        table_name=SHARDED_PREAGGREGATION_RESULTS_TABLE(),
        engine=SHARDED_PREAGGREGATION_RESULTS_TABLE_ENGINE(),
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


def DROP_SHARDED_PREAGGREGATION_RESULTS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_PREAGGREGATION_RESULTS_TABLE()} SYNC"


def TRUNCATE_PREAGGREGATION_RESULTS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_PREAGGREGATION_RESULTS_TABLE()}"

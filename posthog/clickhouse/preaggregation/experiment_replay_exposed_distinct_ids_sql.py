# Table caching an experiment's exposed population expanded to distinct ids.
#
# Replay surfaces list recordings of exposed persons by joining on distinct id, which
# requires expanding exposed person ids through the person-distinct-id mapping. That
# expansion scans the team's whole mapping table, so instead of re-running it on every
# recordings-list request (each load, poll, and pagination page), the expansion is
# computed once per freshness window and its result is stored here.
#
# Rows are written under an opaque cache_key naming one computed generation of one
# experiment's population. Readers always read exactly one generation; superseded
# generations are never read again and expire via TTL.

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "experiment_replay_exposed_distinct_ids"


def DISTRIBUTED_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE():
    return TABLE_BASE_NAME


def SHARDED_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE_ENGINE():
    # ReplacingMergeTree deduplicates rows with the same ORDER BY key, so concurrent
    # writers racing to compute the same generation converge to one row per distinct id.
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,

    -- Opaque key naming one computed generation of one experiment's exposed population
    cache_key String,

    -- One exposed distinct id with its person's first exposure time
    distinct_id String,
    first_exposure_time DateTime64(6, 'UTC'),

    -- When this row was computed (used as ReplacingMergeTree version)
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- TTL: rows are automatically deleted after expires_at. Generations only need to
    -- outlive the freshness marker that points readers at them (minutes), so a day is
    -- a comfortable bound.
    expires_at Date DEFAULT today() + INTERVAL 1 DAY
) ENGINE = {engine}
"""


def SHARDED_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE_SQL():
    return (
        EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, cache_key, distinct_id)
TTL expires_at
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE(),
        engine=SHARDED_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE_ENGINE(),
    )


def DISTRIBUTED_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE_SQL():
    return EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE(),
        engine=Distributed(
            data_table=SHARDED_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE(),
            sharding_key="cityHash64(distinct_id)",
        ),
    )


def DROP_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE()}"


def DROP_SHARDED_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE()} SYNC"


def TRUNCATE_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_EXPERIMENT_REPLAY_EXPOSED_DISTINCT_IDS_TABLE()}"

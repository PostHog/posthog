# Table for storing preaggregated experiment exposures
#
# Instead of scanning the events table on every experiment query to find
# who was exposed to which variant, we compute this once and store it here.
# Subsequent queries read from this table instead of scanning events.
#
# See posthog/hogql_queries/experiments/PREAGGREGATION.md for details.

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "experiment_exposures_preaggregated"


def DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE():
    return TABLE_BASE_NAME


def SHARDED_EXPERIMENT_EXPOSURES_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_EXPERIMENT_EXPOSURES_TABLE_ENGINE():
    # ReplacingMergeTree deduplicates rows with the same ORDER BY key.
    # If we INSERT the same (team_id, job_id, entity_id, breakdown_value) twice,
    # ClickHouse keeps only one row.
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


EXPERIMENT_EXPOSURES_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,

    -- Per-entity exposure data
    entity_id String,
    variant String,
    first_exposure_time DateTime64(6, 'UTC'),
    last_exposure_time DateTime64(6, 'UTC'),
    exposure_event_uuid UUID,
    exposure_session_id String,

    -- Breakdown dimensions (empty array if no breakdown)
    breakdown_value Array(String),

    -- When this row was computed (used as ReplacingMergeTree version)
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- TTL: rows are automatically deleted after expires_at
    expires_at Date DEFAULT today() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_EXPERIMENT_EXPOSURES_TABLE_SQL():
    return (
        EXPERIMENT_EXPOSURES_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, entity_id, breakdown_value)
TTL expires_at
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_EXPERIMENT_EXPOSURES_TABLE(),
        engine=SHARDED_EXPERIMENT_EXPOSURES_TABLE_ENGINE(),
    )


def DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE_SQL():
    return EXPERIMENT_EXPOSURES_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE(),
        engine=Distributed(
            data_table=SHARDED_EXPERIMENT_EXPOSURES_TABLE(),
            sharding_key="cityHash64(entity_id)",
        ),
    )


def DROP_EXPERIMENT_EXPOSURES_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE()}"


def DROP_SHARDED_EXPERIMENT_EXPOSURES_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_EXPERIMENT_EXPOSURES_TABLE()} SYNC"


def TRUNCATE_EXPERIMENT_EXPOSURES_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_EXPERIMENT_EXPOSURES_TABLE()}"

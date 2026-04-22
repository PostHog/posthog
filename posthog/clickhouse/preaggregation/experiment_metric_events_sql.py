# Table for storing preaggregated experiment metric events
#
# Instead of scanning the events table on every experiment query to find
# metric events (funnel steps, mean values, etc.), we compute this once
# and store it here. Subsequent queries read from this table instead of
# scanning events.
#
# For funnels: one row per event per entity per job.
# For mean/ratio: one row per entity per job.
# Deduplicated by ReplacingMergeTree on the full ORDER BY key.
#
# Supported metric types:
# - Funnel: uses `steps` array for step indicators
# - Mean: uses `numeric_value` for the computed metric value
# - Ratio: two separate jobs (numerator + denominator), both use `numeric_value`
#
# Retention is not supported — it uses a different query structure
# (separate start/completion CTEs) and will need its own approach.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree

TABLE_BASE_NAME = "experiment_metric_events_preaggregated"


def DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE():
    return TABLE_BASE_NAME


def SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, ver="computed_at")


EXPERIMENT_METRIC_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,

    -- Per-event data
    entity_id String,
    timestamp DateTime64(6, 'UTC'),
    event_uuid UUID,
    session_id String,

    -- Mean/ratio metrics store the computed value here (default 0 for funnels)
    numeric_value Float64 DEFAULT 0,

    -- Funnel metrics store step indicators here (default empty for non-funnels)
    -- e.g. [1, 0, 1] means this event matches step_0 and step_2
    steps Array(UInt8) DEFAULT [],

    -- When this row was computed (used as ReplacingMergeTree version)
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- TTL: rows are automatically deleted after expires_at
    expires_at Date DEFAULT today() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL():
    return (
        EXPERIMENT_METRIC_EVENTS_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, entity_id, timestamp, event_uuid)
TTL expires_at
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE(),
        engine=SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE_ENGINE(),
    )


def DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL():
    return EXPERIMENT_METRIC_EVENTS_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE(),
        engine=Distributed(
            data_table=SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE(),
            sharding_key="cityHash64(entity_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_EXPERIMENT_METRIC_EVENTS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE()}"


def DROP_SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE()} SYNC"


def TRUNCATE_EXPERIMENT_METRIC_EVENTS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE()}"

# Table for storing lazy-precomputed web analytics Active Hours aggregates
#
# Stores per-hour, per-team aggregate states for the two metrics surfaced by the
# web analytics Active Hours tile: unique users (session-attributed) and total
# pageviews. Reads merge hourly UTC buckets into the (day-of-week, hour-of-day)
# grid the tile renders.
#
# `uniq_users_state` is session-attributed: one INSERT row per (session,
# hourly-bucket-of-session-start), feeding `uniqState(any(person_id))`. This
# matches the web overview semantic where a session's metrics land in the hour
# the session started, so the Active Hours tile's visitor counts line up with
# the rest of the dashboard. Event-bucket attribution is intentionally NOT
# stored — that's a different metric and would need its own column.
#
# `sum_events_state` is event-attributed: one INSERT row per (event,
# hourly-bucket-of-event-timestamp), feeding `sumState(1)`. No session
# aggregation needed — each pageview increments its hour's bucket directly.
#
# Buckets are UTC hourly so reads stay correct for any whole-hour-offset team
# timezone without storing per-team-tz data.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "web_active_hours_preaggregated"


def DISTRIBUTED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME


def SHARDED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,

    -- Hourly UTC bucket. Reads roll this into (toDayOfWeek, toHour) cells in the
    -- team's timezone via toTimeZone(time_window_start, team_tz).
    time_window_start DateTime64(6, 'UTC'),

    -- Session-attributed unique users: one row per session, anchored at the
    -- session's first-event hour. `uniq` (HLL ~99%) matches the v2 / web overview
    -- accuracy/cardinality trade-off and exposes `uniqMergeIf` via HogQL.
    uniq_users_state AggregateFunction(uniq, UUID),

    -- Event-attributed pageview count: one row per event, anchored at the
    -- event's own hour. `sum(1)` so the column is metric-independent — any
    -- count-of-events semantic is supported by combining `sumMergeIf`s.
    sum_events_state AggregateFunction(sum, Int64),

    -- ReplacingMergeTree version column: latest INSERT wins on duplicate ORDER BY keys.
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- Sub-day precision so the framework can attach TTLs like 15 min for "today".
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE_SQL():
    # Partition by `expires_at` (the TTL column) so `ttl_only_drop_parts=1` can
    # drop whole parts atomically when all rows in them expire. Rows for the
    # same UTC day share a partition regardless of which `time_window_start`
    # hour they cover, so mixed-TTL writes (15m for today, 7d for older) end
    # up in distinct parts and the short-TTL parts drop cleanly.
    return (
        WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, time_window_start)
TTL toDateTime(expires_at)
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE(),
        engine=SHARDED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE_ENGINE(),
    )


def DISTRIBUTED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE_SQL():
    # The sharded table lives on the AUX cluster (kept off the main events
    # data nodes — the precompute table is small and read by a narrow set of
    # queries that never JOIN against events). Distributed read table lives
    # on DATA so queries fan out from there and resolve to AUX shards.
    return WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE(),
        engine=Distributed(
            data_table=SHARDED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE(),
            sharding_key="sipHash64(job_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE()}"


def DROP_SHARDED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE()} SYNC"


def TRUNCATE_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE()}"

# Table for storing lazy-precomputed web goals (conversion) aggregates.
#
# One row per (team, job, UTC hour, action_id) where action_id is one of the
# top-5 actions the runner picks at query time
# (`Action.objects…order_by("pinned_at", "-last_calculated_at")[:5]`). The set
# of action expressions and IDs is baked into the INSERT AST and therefore the
# lazy_computation cache key — a different top-5 set yields a different job_id,
# so storing only the integer `action_id` is enough; the action expression
# itself doesn't need to live in the row.
#
# At read time the response is pivoted back to the runner's column layout
# (current/previous count + uniq person tuples per action) using
# `sumStateIf` / `uniqStateIf` keyed by `action_id`.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "web_goals_preaggregated"


def DISTRIBUTED_WEB_GOALS_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME


def SHARDED_WEB_GOALS_PREAGGREGATED_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_WEB_GOALS_PREAGGREGATED_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


WEB_GOALS_PREAGGREGATED_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,

    -- Hourly UTC bucket. Reads filter by [window_start_utc, window_end_utc).
    time_window_start DateTime64(6, 'UTC'),

    -- Django Action.id of the action this row aggregates. The action expression
    -- itself is in the INSERT AST (cache-key shaped), not stored here.
    action_id Int64,

    -- Total match count (sum across sessions in the hour) and unique converting
    -- persons (HLL-estimated). The runner reads top-5 actions only; this table
    -- stores exactly that set per the precompute scope.
    count_state AggregateFunction(sum, Int64),
    unique_persons_state AggregateFunction(uniq, UUID),

    -- ReplacingMergeTree version column: latest INSERT wins on duplicate ORDER BY keys.
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- Sub-day precision so the framework can attach TTLs like 15 min for "today".
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_WEB_GOALS_PREAGGREGATED_TABLE_SQL():
    # Partition by `expires_at` so `ttl_only_drop_parts=1` can drop whole parts
    # atomically as soon as all rows in them expire. Mixed-TTL writes (15m for
    # today, 7d for older) land in distinct parts and the short-TTL parts drop
    # cleanly.
    #
    # ORDER BY puts `action_id` ahead of `time_window_start` because the read
    # pivots metrics per-action and benefits from co-locating rows for a given
    # action. One `job_id` covers exactly one UTC day, so rows under a matched
    # job are within the read's window already — `time_window_start` is a
    # tiebreaker, not a prune key.
    return (
        WEB_GOALS_PREAGGREGATED_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, action_id, time_window_start)
TTL toDateTime(expires_at)
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_WEB_GOALS_PREAGGREGATED_TABLE(),
        engine=SHARDED_WEB_GOALS_PREAGGREGATED_TABLE_ENGINE(),
    )


def DISTRIBUTED_WEB_GOALS_PREAGGREGATED_TABLE_SQL():
    return WEB_GOALS_PREAGGREGATED_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_WEB_GOALS_PREAGGREGATED_TABLE(),
        engine=Distributed(
            data_table=SHARDED_WEB_GOALS_PREAGGREGATED_TABLE(),
            sharding_key="sipHash64(job_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_WEB_GOALS_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_WEB_GOALS_PREAGGREGATED_TABLE()}"


def DROP_SHARDED_WEB_GOALS_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_WEB_GOALS_PREAGGREGATED_TABLE()} SYNC"


def TRUNCATE_WEB_GOALS_PREAGGREGATED_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_WEB_GOALS_PREAGGREGATED_TABLE()}"

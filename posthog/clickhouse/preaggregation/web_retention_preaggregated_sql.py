# Table for lazy-precomputed web analytics retention.
#
# Stores per-(team-tz activity day, first-seen cohort week) person uniq states.
# A read merges the states of an activity week's seven day-buckets into the
# retained-user count for one (cohort week, week offset) matrix cell, so any
# weekly first-occurrence retention matrix over covered days can be assembled
# without rescanning events.
#
# The bucket key `time_window_start` is `toStartOfDay(event.timestamp, team_tz)`
# — the framework's daily job windows — while `cohort_week_start` is the
# team-local week of the person's first matching event over full history. Daily
# (not weekly) buckets keep the job windows aligned with every other lazy
# family, and uniq-state merges across the days of a week are exact.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "web_retention_preaggregated"


def DISTRIBUTED_WEB_RETENTION_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME


def SHARDED_WEB_RETENTION_PREAGGREGATED_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_WEB_RETENTION_PREAGGREGATED_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


WEB_RETENTION_PREAGGREGATED_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,

    -- Daily bucket keyed by `toStartOfDay(event.timestamp, team_tz)` — start
    -- of the team-local day the person was active on.
    time_window_start DateTime64(6, 'UTC'),

    -- Team-local week (team week-start mode) of the person's first matching
    -- event over full history. A person's rows carry the same cohort week in
    -- every activity bucket, so cohort size falls out of the offset-0 cell.
    cohort_week_start DateTime64(6, 'UTC'),

    -- Persons active in this day bucket whose first occurrence fell in
    -- `cohort_week_start`. Merging across the days of one activity week
    -- yields the retained-user count for that (cohort, offset) cell.
    retained_users_state AggregateFunction(uniq, UUID),

    -- ReplacingMergeTree version column: latest INSERT wins on duplicate ORDER BY keys.
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- Sub-day precision so the framework can attach TTLs like 15 min for "today".
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_WEB_RETENTION_PREAGGREGATED_TABLE_SQL():
    # Partition by `expires_at` (the TTL column) so `ttl_only_drop_parts=1` can
    # drop whole parts atomically when all rows in them expire.
    # `cohort_week_start` must be in ORDER BY so the ReplacingMergeTree does
    # not collapse distinct cohorts within one (job, day).
    return (
        WEB_RETENTION_PREAGGREGATED_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, time_window_start, cohort_week_start)
TTL toDateTime(expires_at)
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_WEB_RETENTION_PREAGGREGATED_TABLE(),
        engine=SHARDED_WEB_RETENTION_PREAGGREGATED_TABLE_ENGINE(),
    )


def DISTRIBUTED_WEB_RETENTION_PREAGGREGATED_TABLE_SQL():
    # The sharded table lives on the AUX cluster (kept off the main events
    # data nodes — the precompute table is small and read by a narrow set of
    # queries that never JOIN against events). Distributed read table lives
    # on DATA so queries fan out from there and resolve to AUX shards.
    return WEB_RETENTION_PREAGGREGATED_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_WEB_RETENTION_PREAGGREGATED_TABLE(),
        engine=Distributed(
            data_table=SHARDED_WEB_RETENTION_PREAGGREGATED_TABLE(),
            sharding_key="sipHash64(job_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_WEB_RETENTION_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_WEB_RETENTION_PREAGGREGATED_TABLE()}"


def DROP_SHARDED_WEB_RETENTION_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_WEB_RETENTION_PREAGGREGATED_TABLE()} SYNC"

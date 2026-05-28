# Pre-aggregated table for retention insight queries.
#
# Stores one row per (team_id, job_id, day, actor_id, event), capturing the earliest
# timestamp the actor fired that event on that day. Retention queries read across the
# daily windows the cohort covers, GROUP BY actor_id, and reconstruct the same retention
# buckets they'd compute from raw events — but against a table that's typically ~10x
# smaller per team-day. Tractability and read shape validated in the prototype; see
# `.planning/retention-preagg-prototype.md`.
#
# Lives on AUX (kept off the main events DATA nodes). The table is small relative to
# events and read by a narrow set of queries that never JOIN against events directly —
# person override resolution happens in the read query via the standard
# `person_distinct_id_overrides` join, against the (small) overrides table.
#
# Engine note: ReplacingMergeTree(computed_at) is the correct fit here because
# re-materialisation of a day (e.g. after a late-arriving event lands past the seal)
# emits a new job_id whose rows have a later computed_at and replace the prior job's
# rows on read. AggregatingMergeTree was considered but is overkill — every late
# materialisation re-scans the day from raw events, so we always have the canonical
# first_ts per (team, day, actor, event) in the row, no merge state needed.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "retention_actor_event_day"


def DISTRIBUTED_RETENTION_ACTOR_EVENT_DAY_TABLE() -> str:
    return TABLE_BASE_NAME


def SHARDED_RETENTION_ACTOR_EVENT_DAY_TABLE() -> str:
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_RETENTION_ACTOR_EVENT_DAY_TABLE_ENGINE() -> ReplacingMergeTree:
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


RETENTION_ACTOR_EVENT_DAY_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id            Int64,
    job_id             UUID,

    -- Daily UTC bucket; reads filter by [date_from, date_to). Day granularity is the
    -- finest retention shows in the UI, and matches the per-day grouping in the raw
    -- events retention path (`toStartOfDay(timestamp)`).
    day                Date,

    -- Actor identity. Raw `events.person_id` — overrides resolved at READ time via
    -- the same `events__override` join the raw events retention path uses, so a
    -- person merge after this row is written stays correct without re-materialisation.
    actor_id           UUID,

    -- Retention aggregation target. -1 = person retention (the default); 0..4 = group
    -- retention by group_type_index. Group retention's `$group_N` column is captured
    -- in actor_id when group_type_index >= 0.
    group_type_index   Int8 DEFAULT -1,

    -- Event name. LowCardinality halves on-disk size since teams typically retain
    -- against a small set of events ($pageview, $screen, etc.) even when their
    -- overall event volume is high.
    event              LowCardinality(String),

    -- Earliest timestamp this (team, day, actor, event) was observed at. Used by
    -- first-occurrence-matching-filters retention to compute the actor's cohort
    -- anchor day across the queried window: `min(first_ts)` over the actor's days.
    first_ts           DateTime64(6, 'UTC'),

    -- ReplacingMergeTree version. Re-materialisation of a (team, day) bumps the
    -- job_id and writes rows with a later computed_at; reads filter to
    -- `job_id IN (latest set)` so the newer materialisation wins.
    computed_at        DateTime64(6, 'UTC') DEFAULT now(),

    -- Sub-day TTL so the framework can attach short TTLs (e.g. 15 min for "today")
    -- and have parts drop atomically when all rows in them expire.
    expires_at         DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_RETENTION_ACTOR_EVENT_DAY_TABLE_SQL() -> str:
    # PARTITION BY expires_at (the TTL column) so ttl_only_drop_parts=1 can drop
    # whole parts atomically when every row in them expires.
    #
    # ORDER BY (team_id, job_id, day, event, group_type_index, actor_id) matches the
    # canonical read shape: filter on team_id + job_id IN (...) + day range + event,
    # GROUP BY actor_id. actor_id is last so the index isn't bloated by per-actor
    # cardinality; reads scan the (team, job, day, event) prefix and stream actors.
    return (
        RETENTION_ACTOR_EVENT_DAY_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, day, event, group_type_index, actor_id)
TTL toDateTime(expires_at)
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_RETENTION_ACTOR_EVENT_DAY_TABLE(),
        engine=SHARDED_RETENTION_ACTOR_EVENT_DAY_TABLE_ENGINE(),
    )


def DISTRIBUTED_RETENTION_ACTOR_EVENT_DAY_TABLE_SQL() -> str:
    # Sharded table on AUX, distributed read table also targets AUX. sipHash64 on
    # (team_id, actor_id) keeps an actor's days co-located on one shard — retention
    # GROUP BY actor_id then runs locally per shard with a final coordinator merge.
    return RETENTION_ACTOR_EVENT_DAY_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_RETENTION_ACTOR_EVENT_DAY_TABLE(),
        engine=Distributed(
            data_table=SHARDED_RETENTION_ACTOR_EVENT_DAY_TABLE(),
            sharding_key="sipHash64(team_id, actor_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_RETENTION_ACTOR_EVENT_DAY_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_RETENTION_ACTOR_EVENT_DAY_TABLE()}"


def DROP_SHARDED_RETENTION_ACTOR_EVENT_DAY_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {SHARDED_RETENTION_ACTOR_EVENT_DAY_TABLE()} SYNC"


def TRUNCATE_RETENTION_ACTOR_EVENT_DAY_TABLE_SQL() -> str:
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_RETENTION_ACTOR_EVENT_DAY_TABLE()}"

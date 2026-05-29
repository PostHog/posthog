# Per-person retention-curve table for retention insight queries.
#
# Scope (v1): page-view and "all events" retention, serving the first-occurrence shapes
# (`retention_first_time` + `retention_first_ever_occurrence`) that own retention p95.
# One row per (team_id, kind, person_id): the person's first qualifying day across ALL
# history (`first_seen_day`) plus the day-offsets since then on which they were active
# (`active_offsets`). That single row is the person's whole retention curve — the cohort
# (first_seen_day) and the return pattern (offsets) — so a first-occurrence read scans only
# new users in the window and reads returns straight off the row, no events scan.
#
# Storing `first_seen_day` from full history is the point: it makes cohort assignment exact,
# fixing the "looks-new-but-isn't" error a windowed materialisation hits when a person's
# true first event predates the queried range.
#
# Lives on AUX (kept off the main events DATA nodes). Never JOINed against events; person
# override resolution happens at READ time (v1 reads raw person_id — merge handling is a
# follow-up).
#
# Engine: ReplacingMergeTree(computed_at). Re-materialisation re-derives a person's whole
# curve and writes a row with a later computed_at that replaces the prior one on read.
# `first_seen_day` is immutable per person, so every version of a row shares a partition
# (PARTITION BY toYYYYMM(first_seen_day)) and dedups correctly.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "retention_curve"

# Marker stored in the `kind` column for "all events" retention rows: the person's first
# activity in ANY event, and offsets from it. Lets all-events retention read a compact
# per-person slice instead of scanning every event.
ALL_EVENTS_KIND = "$$all_events"


def DISTRIBUTED_RETENTION_CURVE_TABLE() -> str:
    return TABLE_BASE_NAME


def SHARDED_RETENTION_CURVE_TABLE() -> str:
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_RETENTION_CURVE_TABLE_ENGINE() -> ReplacingMergeTree:
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


RETENTION_CURVE_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id        Int64,

    -- Retention entity: a real event name ('$pageview') or the all-events marker.
    -- LowCardinality since teams retain against a small set of kinds.
    kind           LowCardinality(String),

    -- Actor identity. Raw `events.person_id` — overrides resolved at READ time, so a person
    -- merge after this row is written stays correct without re-materialisation (v1 reads the
    -- raw id; read-time override regrouping is a follow-up).
    person_id      UUID,

    -- The person's first qualifying day for this kind, across all history. Determines their
    -- cohort period. Immutable once set.
    first_seen_day Date,

    -- Day-offsets since first_seen_day on which the person was active in this kind, sorted
    -- and capped at the horizon. 0 is always present (their first day). day/week/month
    -- retention all derive from these day-offsets at read time.
    active_offsets Array(UInt16),

    -- ReplacingMergeTree version. A re-materialisation re-derives the whole curve and writes
    -- a row with a later computed_at; the newer row wins on read.
    computed_at    DateTime64(6, 'UTC') DEFAULT now64(6, 'UTC')
) ENGINE = {engine}
"""


def SHARDED_RETENTION_CURVE_TABLE_SQL() -> str:
    # ORDER BY (team_id, kind, first_seen_day, person_id) matches the read shape: filter
    # team_id + kind + first_seen_day ∈ window, GROUP BY person_id. first_seen_day before
    # person_id makes the cohort window a contiguous prefix scan.
    #
    # PARTITION BY toYYYYMM(first_seen_day): first_seen_day is immutable per person, so all
    # versions of a person's row land in the same partition and ReplacingMergeTree dedups
    # them on merge.
    return (
        RETENTION_CURVE_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMM(first_seen_day)
ORDER BY (team_id, kind, first_seen_day, person_id)
SETTINGS index_granularity=8192
"""
    ).format(
        table_name=SHARDED_RETENTION_CURVE_TABLE(),
        engine=SHARDED_RETENTION_CURVE_TABLE_ENGINE(),
    )


def DISTRIBUTED_RETENTION_CURVE_TABLE_SQL() -> str:
    # Sharded table on AUX, distributed read table also targets AUX. sipHash64 on
    # (team_id, person_id) keeps a person's row on one shard so the GROUP BY person_id runs
    # locally per shard with a final coordinator merge.
    return RETENTION_CURVE_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_RETENTION_CURVE_TABLE(),
        engine=Distributed(
            data_table=SHARDED_RETENTION_CURVE_TABLE(),
            sharding_key="sipHash64(team_id, person_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_RETENTION_CURVE_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_RETENTION_CURVE_TABLE()}"


def DROP_SHARDED_RETENTION_CURVE_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {SHARDED_RETENTION_CURVE_TABLE()} SYNC"


def TRUNCATE_RETENTION_CURVE_TABLE_SQL() -> str:
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_RETENTION_CURVE_TABLE()}"

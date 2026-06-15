# Per-person retention pre-aggregation table for the retention insight read path.
#
# One row per (team_id, kind, actor_id) holding two composable aggregate states:
#   - first_seen: minState of the actor's first qualifying timestamp across ALL history
#     (their cohort anchor). minMerge is the all-history minimum, so cohort assignment is
#     exact with no windowed "looks-new-but-isn't" error, and no separate anchor table.
#   - active_days: a set-state over ABSOLUTE day-numbers (toUInt32(toDate(ts))) the actor was
#     active in this kind. Absolute (not offsets from first_seen) so the set unions cleanly
#     under person-merge and is stable when a late, earlier event lowers first_seen.
# Returns for day/week/month all derive from active_days at read time.
#
# Engine: AggregatingMergeTree. State columns merge independently and idempotently, so the
# table is fed incrementally (a later event loses on min / is absorbed on set-union) without
# re-deriving the whole row. There is NO time PARTITION BY: a per-actor row accumulates inserts
# across all time and must co-locate to merge, so any time partition would scatter and break it.
#
# Lives on AUX (off the main events DATA nodes); never JOINed against events on the hot path.
# Sharded by sipHash64(team_id, actor_id) so an actor's row resolves to one shard.

from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

TABLE_BASE_NAME = "retention_actor"

# Marker stored in `kind` for all-events retention: the actor was active in ANY event.
ALL_EVENTS_KIND = "$$all_events"


def DISTRIBUTED_RETENTION_ACTOR_TABLE() -> str:
    return TABLE_BASE_NAME


def SHARDED_RETENTION_ACTOR_TABLE() -> str:
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_RETENTION_ACTOR_TABLE_ENGINE() -> AggregatingMergeTree:
    return AggregatingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED)


RETENTION_ACTOR_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id     Int64,

    -- Retention entity: a real event name ('$pageview') or the all-events marker.
    kind        LowCardinality(String),

    -- Actor identity. Raw `events.person_id`; overrides resolved at materialisation time.
    actor_id    UUID,

    -- All-history first qualifying timestamp (cohort anchor). Read with minMerge(first_seen).
    first_seen  AggregateFunction(min, DateTime64(6, 'UTC')),

    -- Set of absolute active day-numbers (toUInt32(toDate(ts))). Read with
    -- groupUniqArrayMerge(active_days); horizon cap is applied at materialisation, not here.
    active_days AggregateFunction(groupUniqArray, UInt32)
) ENGINE = {engine}
"""


def SHARDED_RETENTION_ACTOR_TABLE_SQL() -> str:
    # ORDER BY (team_id, kind, actor_id): reads filter team_id + kind and GROUP BY actor_id to
    # merge each actor's states. No PARTITION BY — see module header (per-actor rows must
    # co-locate to merge; the table is people-bounded, not a time series).
    return (
        RETENTION_ACTOR_TABLE_BASE_SQL
        + """
ORDER BY (team_id, kind, actor_id)
SETTINGS index_granularity=8192
"""
    ).format(
        table_name=SHARDED_RETENTION_ACTOR_TABLE(),
        engine=SHARDED_RETENTION_ACTOR_TABLE_ENGINE(),
    )


def DISTRIBUTED_RETENTION_ACTOR_TABLE_SQL() -> str:
    # Sharded table on AUX; distributed read table also targets AUX. sipHash64(team_id, actor_id)
    # keeps an actor's row on one shard so GROUP BY actor_id runs locally per shard.
    return RETENTION_ACTOR_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_RETENTION_ACTOR_TABLE(),
        engine=Distributed(
            data_table=SHARDED_RETENTION_ACTOR_TABLE(),
            sharding_key="sipHash64(team_id, actor_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_RETENTION_ACTOR_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_RETENTION_ACTOR_TABLE()}"


def DROP_SHARDED_RETENTION_ACTOR_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {SHARDED_RETENTION_ACTOR_TABLE()} SYNC"


def TRUNCATE_RETENTION_ACTOR_TABLE_SQL() -> str:
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_RETENTION_ACTOR_TABLE()}"

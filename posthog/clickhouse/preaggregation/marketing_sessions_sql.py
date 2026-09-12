# Session-grain precompute for marketing analytics attribution.
#
# The sibling tables aggregate by dimension, so the person survives only as a `uniq` state. The
# credit side of attribution walks each converting person's touchpoints in order and needs them
# individually, so this table keeps one row per session with `person_id` un-aggregated.
#
# `channel_type` is stored already classified. Resolving it at read time is what makes these queries
# expensive: over 5.8M sessions, reading the ingredients costs 857 MiB and classifying them costs
# 4.24 GiB.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "marketing_sessions_dimensional_preaggregated"


def DISTRIBUTED_MARKETING_SESSIONS_TABLE():
    return TABLE_BASE_NAME


def SHARDED_MARKETING_SESSIONS_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_MARKETING_SESSIONS_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


MARKETING_SESSIONS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,

    period_bucket DateTime,

    session_id String,

    person_id UUID,

    -- The event bounds let a read agree with the live path, which bounds by event time rather than
    -- by session start.
    start_timestamp DateTime64(6, 'UTC'),
    min_event_timestamp DateTime64(6, 'UTC'),
    max_event_timestamp DateTime64(6, 'UTC'),

    channel_type String,

    utm_source String,
    utm_medium String,
    utm_campaign String,
    utm_term String,
    utm_content String,
    referring_domain String,
    entry_pathname String,

    computed_at DateTime64(6, 'UTC') DEFAULT now(),
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_MARKETING_SESSIONS_TABLE_SQL():
    # Person first, unlike the sibling tables: the credit read groups by person and walks each one's
    # sessions in time order, so that is the prefix it needs.
    return (
        MARKETING_SESSIONS_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, person_id, start_timestamp, session_id)
TTL toDateTime(expires_at) + INTERVAL 1 DAY
SETTINGS ttl_only_drop_parts = 1, index_granularity = 8192
"""
    ).format(
        table_name=SHARDED_MARKETING_SESSIONS_TABLE(),
        engine=SHARDED_MARKETING_SESSIONS_TABLE_ENGINE(),
    )


def DISTRIBUTED_MARKETING_SESSIONS_TABLE_SQL():
    return MARKETING_SESSIONS_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_MARKETING_SESSIONS_TABLE(),
        engine=Distributed(
            data_table=SHARDED_MARKETING_SESSIONS_TABLE(),
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
            sharding_key="cityHash64(person_id)",
        ),
    )


def DROP_MARKETING_SESSIONS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_MARKETING_SESSIONS_TABLE()}"


def DROP_SHARDED_MARKETING_SESSIONS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_MARKETING_SESSIONS_TABLE()} SYNC"


def TRUNCATE_MARKETING_SESSIONS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_MARKETING_SESSIONS_TABLE()}"

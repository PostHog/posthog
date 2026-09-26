"""ClickHouse schema for the shared alerts platform's check history.

One row per check, written by the platform's record activity. The Python definitions here mirror
the declarative schema in `posthog/clickhouse/hcl/`, which is the source of truth; these exist so
`posthog/clickhouse/schema.py` can build the table in a local or test ClickHouse.
"""

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

PLATFORM_ALERT_EVENTS_TABLE = "platform_alert_events"
SHARDED_PLATFORM_ALERT_EVENTS_TABLE = f"sharded_{PLATFORM_ALERT_EVENTS_TABLE}"

# `inserted_at` is the version column, so a retried record of the same evaluation replaces the row
# rather than adding one. It is separate from `expires_at` on purpose: overloading the retention
# column as the version inverts the winner as soon as one insert path computes a different TTL.
PLATFORM_ALERT_EVENTS_TTL_DAYS = 90

BASE_PLATFORM_ALERT_EVENTS_COLUMNS = """
    team_id Int64,
    configuration_id UUID,
    alert_id UUID,
    grouping_key String,
    evaluation_key String,
    kind LowCardinality(String),
    alert_name String,
    previous_state LowCardinality(String),
    state LowCardinality(String),
    value Nullable(Float64),
    labels Map(String, String),
    condition_snapshot String,
    source_config_snapshot String,
    query_duration_ms Nullable(UInt32),
    error_message String,
    consecutive_failures UInt32,
    muted_notification LowCardinality(String),
    occurred_at DateTime64(6, 'UTC'),
    expires_at DateTime64(6, 'UTC') DEFAULT now64(6) + toIntervalDay({ttl_days}),
    inserted_at DateTime64(6, 'UTC') DEFAULT now64(6)
""".strip()


def platform_alert_events_table_engine() -> ReplacingMergeTree:
    # REPLICATED, not SHARDED: aux is a single shard with replicas, and this is the scheme whose
    # ZooKeeper path matches what the declarative schema declares for this table.
    return ReplacingMergeTree(
        PLATFORM_ALERT_EVENTS_TABLE,
        replication_scheme=ReplicationScheme.REPLICATED,
        ver="inserted_at",
    )


def SHARDED_PLATFORM_ALERT_EVENTS_TABLE_SQL() -> str:
    # The sort key serves three reads: delivery resolving one evaluation by
    # (configuration_id, evaluation_key), a source rebuilding an N-of-M window from the last rows of
    # one alert, and a comparison scanning a team over a time range.
    #
    # Partitioned on `occurred_at` because ReplacingMergeTree only deduplicates within a partition,
    # and `occurred_at` is the batch cutoff, so a retry recomputes it and lands in the same one.
    # The TTL still reads `expires_at`, which is insert time and so is independent of a frozen clock.
    return f"""
CREATE TABLE IF NOT EXISTS {SHARDED_PLATFORM_ALERT_EVENTS_TABLE}
(
    {BASE_PLATFORM_ALERT_EVENTS_COLUMNS.format(ttl_days=PLATFORM_ALERT_EVENTS_TTL_DAYS)}
)
ENGINE = {platform_alert_events_table_engine()}
ORDER BY (team_id, configuration_id, alert_id, occurred_at, evaluation_key)
PARTITION BY toYYYYMM(occurred_at)
TTL toDateTime(expires_at)
SETTINGS index_granularity = 8192
"""


def DISTRIBUTED_PLATFORM_ALERT_EVENTS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {PLATFORM_ALERT_EVENTS_TABLE}
(
    {BASE_PLATFORM_ALERT_EVENTS_COLUMNS.format(ttl_days=PLATFORM_ALERT_EVENTS_TTL_DAYS)}
)
ENGINE = {
        Distributed(
            data_table=SHARDED_PLATFORM_ALERT_EVENTS_TABLE,
            sharding_key="cityHash64(team_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        )
    }
"""

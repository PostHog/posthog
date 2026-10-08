"""ClickHouse schema for the shared alerts platform's check history.

One row per check, written by the platform's record activity. The Python definitions here mirror
the declarative schema in `posthog/clickhouse/hcl/`, which is the source of truth; these exist so
`posthog/clickhouse/schema.py` can build the table in a local or test ClickHouse.
"""

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme

PLATFORM_ALERT_EVENTS_TABLE = "platform_alert_events"
SHARDED_PLATFORM_ALERT_EVENTS_TABLE = f"sharded_{PLATFORM_ALERT_EVENTS_TABLE}"

PLATFORM_ALERT_EVENTS_TTL_DAYS = 90

BASE_PLATFORM_ALERT_EVENTS_COLUMNS = f"""
    team_id Int64,
    configuration_id UUID,
    alert_id UUID,
    grouping_key String,
    evaluation_key String,
    kind LowCardinality(String),
    alert_name String,
    previous_state LowCardinality(String),
    state LowCardinality(String),
    episode_started_at Nullable(DateTime64(6, 'UTC')),
    value Nullable(Float64),
    labels Map(String, String),
    condition_snapshot String,
    source_config_snapshot String,
    query_duration_ms Nullable(UInt32),
    error_message String,
    consecutive_failures UInt32,
    muted_notification LowCardinality(String),
    occurred_at DateTime64(6, 'UTC'),
    source_kind LowCardinality(String),
    expires_at Date DEFAULT today() + toIntervalDay({PLATFORM_ALERT_EVENTS_TTL_DAYS})
""".strip()


def platform_alert_events_table_engine() -> MergeTreeEngine:
    # REPLICATED, not SHARDED: aux is a single shard with replicas, and this is the scheme whose
    # ZooKeeper path matches what the declarative schema declares for this table.
    return MergeTreeEngine(
        PLATFORM_ALERT_EVENTS_TABLE,
        replication_scheme=ReplicationScheme.REPLICATED,
    )


def SHARDED_PLATFORM_ALERT_EVENTS_TABLE_SQL() -> str:
    # A plain MergeTree because every row is a distinct check and nothing supersedes anything. The
    # one duplicate this table can see is a retried insert of an identical batch, which the
    # replicated engine drops through its own insert deduplication; the writer keys that
    # explicitly. A ReplacingMergeTree would instead make every count over the table wrong on any
    # part a merge has not reached, and ClickHouse never promises a merge will run.
    #
    # `expires_at` is insert time rather than `occurred_at` plus the TTL, so a backfill of old
    # checks does not land rows that are already expired. Rows in one part then expire together,
    # which is what makes `ttl_only_drop_parts` a part drop rather than a rewrite of every column.
    #
    # The sort key is declared in the HCL, which is the source of truth; the rationale for its
    # shape lives there.
    return f"""
CREATE TABLE IF NOT EXISTS {SHARDED_PLATFORM_ALERT_EVENTS_TABLE}
(
    {BASE_PLATFORM_ALERT_EVENTS_COLUMNS}
)
ENGINE = {platform_alert_events_table_engine()}
ORDER BY (team_id, configuration_id, alert_id, occurred_at, evaluation_key)
PRIMARY KEY (team_id, configuration_id, alert_id, occurred_at)
PARTITION BY toYYYYMM(occurred_at)
TTL expires_at
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1
"""


def DISTRIBUTED_PLATFORM_ALERT_EVENTS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {PLATFORM_ALERT_EVENTS_TABLE}
(
    {BASE_PLATFORM_ALERT_EVENTS_COLUMNS}
)
ENGINE = {
        Distributed(
            data_table=SHARDED_PLATFORM_ALERT_EVENTS_TABLE,
            sharding_key="cityHash64(team_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        )
    }
"""

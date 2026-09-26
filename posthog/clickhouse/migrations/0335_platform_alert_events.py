"""AUTO-GENERATED from the declarative HCL by posthog/clickhouse/hcl/codegen/gen_migration.py.
Placement (node_roles) is derived from the node composition manifest; review before committing.
"""

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [
    run_sql_with_exceptions(
        "CREATE TABLE IF NOT EXISTS posthog.sharded_platform_alert_events (\n  team_id Int64,\n  configuration_id UUID,\n  alert_id UUID,\n  grouping_key String,\n  evaluation_key String,\n  kind LowCardinality(String),\n  alert_name String,\n  previous_state LowCardinality(String),\n  state LowCardinality(String),\n  value Nullable(Float64),\n  labels Map(String, String),\n  condition_snapshot String,\n  source_config_snapshot String,\n  query_duration_ms Nullable(UInt32),\n  error_message String,\n  consecutive_failures UInt32,\n  muted_notification LowCardinality(String),\n  occurred_at DateTime64(6, 'UTC'),\n  expires_at DateTime64(6, 'UTC') DEFAULT now64(6) + toIntervalDay(90),\n  inserted_at DateTime64(6, 'UTC') DEFAULT now64(6)\n) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.platform_alert_events', '{replica}-{shard}', inserted_at) ORDER BY (team_id, configuration_id, alert_id, occurred_at, evaluation_key) PARTITION BY toYYYYMM(occurred_at) TTL toDateTime(expires_at) SETTINGS index_granularity = 8192",
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        "CREATE TABLE IF NOT EXISTS posthog.platform_alert_events (\n  team_id Int64,\n  configuration_id UUID,\n  alert_id UUID,\n  grouping_key String,\n  evaluation_key String,\n  kind LowCardinality(String),\n  alert_name String,\n  previous_state LowCardinality(String),\n  state LowCardinality(String),\n  value Nullable(Float64),\n  labels Map(String, String),\n  condition_snapshot String,\n  source_config_snapshot String,\n  query_duration_ms Nullable(UInt32),\n  error_message String,\n  consecutive_failures UInt32,\n  muted_notification LowCardinality(String),\n  occurred_at DateTime64(6, 'UTC'),\n  expires_at DateTime64(6, 'UTC') DEFAULT now64(6) + toIntervalDay(90),\n  inserted_at DateTime64(6, 'UTC') DEFAULT now64(6)\n) ENGINE = Distributed('aux', 'posthog', 'sharded_platform_alert_events', cityHash64(team_id))",
        node_roles=[NodeRole.DATA, NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]

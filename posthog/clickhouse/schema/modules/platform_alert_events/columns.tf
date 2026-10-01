# Column lists that more than one object uses.

locals {
  sharded_platform_alert_events_columns = [
    { name = "team_id", type = "Int64" },
    { name = "configuration_id", type = "UUID" },
    { name = "alert_id", type = "UUID" },
    { name = "grouping_key", type = "String" },
    { name = "evaluation_key", type = "String" },
    { name = "kind", type = "LowCardinality(String)" },
    { name = "alert_name", type = "String" },
    { name = "previous_state", type = "LowCardinality(String)" },
    { name = "state", type = "LowCardinality(String)" },
    { name = "episode_started_at", type = "Nullable(DateTime64(6, 'UTC'))" },
    { name = "value", type = "Nullable(Float64)" },
    { name = "labels", type = "Map(String, String)" },
    { name = "condition_snapshot", type = "String" },
    { name = "source_config_snapshot", type = "String" },
    { name = "query_duration_ms", type = "Nullable(UInt32)" },
    { name = "error_message", type = "String" },
    { name = "consecutive_failures", type = "UInt32" },
    { name = "muted_notification", type = "LowCardinality(String)" },
    { name = "occurred_at", type = "DateTime64(6, 'UTC')" },
    { name = "expires_at", type = "Date", default_expression = "today() + toIntervalDay(90)" },
  ]
}

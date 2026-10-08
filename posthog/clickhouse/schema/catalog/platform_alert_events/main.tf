variable "node" {
  description = "The server these objects live on: { name, host, port, leader }. Null puts them on the provider's host."
  type        = any
  default     = null
}

variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "ttl" {
  description = "Set table TTLs. Tests turn them off, because they insert rows with old timestamps."
  type        = bool
  default     = true
}

variable "objects" {
  description = "Names of the objects to create."
  type        = set(string)
}

variable "test" {
  description = "Use the definitions the test suite expects."
  type        = bool
  default     = false
}

variable "deployment" { type = any }

locals {
  deployment = merge({ overrides = {} }, var.deployment)
}

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
    { name = "source_kind", type = "LowCardinality(String)" },
    { name = "expires_at", type = "Date", default_expression = "today() + toIntervalDay(90)" },
  ]
}

module "sharded_platform_alert_events_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "platform_alert_events"
  database = var.database
  layout   = "global"
  columns  = local.sharded_platform_alert_events_columns
  storage = {
    partition_by = "toYYYYMM(occurred_at)"
    primary_key  = "(team_id, configuration_id, alert_id, occurred_at)"
    order_by     = "(team_id, configuration_id, alert_id, occurred_at, evaluation_key)"
    ttl          = var.ttl ? "expires_at" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    read = true
  }
  sharding_key = "cityHash64(team_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.platform_alert_events"
    cluster     = "aux"
  }, local.deployment)
  names = { storage = "sharded_platform_alert_events" }
}

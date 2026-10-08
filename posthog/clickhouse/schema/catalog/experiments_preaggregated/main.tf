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
  sharded_experiment_metric_events_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "entity_id", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "event_uuid", type = "UUID" },
    { name = "session_id", type = "String" },
    { name = "numeric_value", type = "Float64", default_expression = "0" },
    { name = "steps", type = "Array(UInt8)", default_expression = "[]" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "Date", default_expression = "today() + toIntervalDay(7)" },
  ]

  sharded_experiment_exposures_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "entity_id", type = "String" },
    { name = "variant", type = "String" },
    { name = "first_exposure_time", type = "DateTime64(6, 'UTC')" },
    { name = "last_exposure_time", type = "DateTime64(6, 'UTC')" },
    { name = "exposure_event_uuid", type = "UUID" },
    { name = "exposure_session_id", type = "String" },
    { name = "breakdown_value", type = "Array(String)" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "Date", default_expression = "today() + toIntervalDay(7)" },
  ]
}

module "sharded_experiment_exposures_preaggregated_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "experiment_exposures_preaggregated"
  database = var.database
  columns  = local.sharded_experiment_exposures_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, entity_id, breakdown_value)"
    ttl          = var.ttl ? "expires_at" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    write = false
  }
  sharding_key = "cityHash64(entity_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.experiment_exposures_preaggregated"
    cluster     = "posthog"
  }, local.deployment)
}

module "sharded_experiment_metric_events_preaggregated_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "experiment_metric_events_preaggregated"
  database = var.database
  layout   = "global"
  columns  = local.sharded_experiment_metric_events_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, entity_id, timestamp, event_uuid)"
    ttl          = var.ttl ? "expires_at" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    read = true
  }
  sharding_key = "cityHash64(entity_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.experiment_metric_events_preaggregated"
    cluster     = "aux"
  }, local.deployment)
  names = { storage = "sharded_experiment_metric_events_preaggregated" }
}

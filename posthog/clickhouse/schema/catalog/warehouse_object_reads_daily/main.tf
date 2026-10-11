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
  warehouse_object_reads_daily_columns = [
    { name = "team_id", type = "Int64" },
    { name = "day", type = "Date" },
    { name = "read_kind", type = "Enum8('read' = 1, 'refresh' = 2)" },
    { name = "subject_kind", type = "Enum8('saved_query' = 1, 'table' = 2)" },
    { name = "subject_id", type = "String" },
    { name = "workflow_id", type = "String" },
    { name = "lc_kind", type = "LowCardinality(String)" },
    { name = "lc_product", type = "LowCardinality(String)" },
    { name = "lc_feature", type = "LowCardinality(String)" },
    { name = "lc_access_method", type = "LowCardinality(String)" },
    { name = "source", type = "LowCardinality(String)" },
    { name = "scene", type = "LowCardinality(String)" },
    { name = "has_user_id", type = "Bool" },
    { name = "read_alone", type = "Bool" },
    { name = "requests", type = "AggregateFunction(uniq, String)" },
    { name = "users", type = "AggregateFunction(uniq, Int64)" },
    { name = "read_count", type = "SimpleAggregateFunction(sum, UInt64)" },
    { name = "duration_ms_sum", type = "SimpleAggregateFunction(sum, UInt64)" },
    { name = "read_bytes_sum", type = "SimpleAggregateFunction(sum, UInt64)" },
    { name = "duration_ms_quantiles", type = "AggregateFunction(quantiles(0.5, 0.9), UInt64)" },
    { name = "read_bytes_quantiles", type = "AggregateFunction(quantiles(0.5, 0.9), UInt64)" },
    { name = "max_event_time", type = "SimpleAggregateFunction(max, DateTime)" },
  ]

  warehouse_object_reads_daily_storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toYYYYMMDD(day)"
    order_by     = "(team_id, day, read_kind, subject_kind, subject_id, workflow_id, lc_kind, lc_product, lc_feature, lc_access_method, source, scene, has_user_id, read_alone)"
    ttl          = var.ttl ? "day + toIntervalDay(60)" : null
    settings     = "ttl_only_drop_parts = 1"
  }
}

module "warehouse_object_reads_daily_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "warehouse_object_reads_daily"
  database = var.database
  layout   = "global"
  columns  = local.warehouse_object_reads_daily_columns
  storage  = local.warehouse_object_reads_daily_storage
  routing = {
    read = true
  }
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.warehouse_object_reads_daily"
    cluster     = "aux"
  }, local.deployment)
  names = { storage = "sharded_warehouse_object_reads_daily" }
}

module "warehouse_object_reads_daily_staging_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "warehouse_object_reads_daily_staging"
  database = var.database
  layout   = "global"
  columns  = local.warehouse_object_reads_daily_columns
  storage  = local.warehouse_object_reads_daily_storage
  deployment = merge({
    cluster = "aux"
  }, local.deployment)
  names = { storage = "sharded_warehouse_object_reads_daily_staging" }
}

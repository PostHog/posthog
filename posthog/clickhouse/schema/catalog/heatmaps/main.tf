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
  kafka_heatmaps_columns = [
    { name = "session_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "x", type = "Int16" },
    { name = "y", type = "Int16" },
    { name = "scale_factor", type = "Int16" },
    { name = "viewport_width", type = "Int16" },
    { name = "viewport_height", type = "Int16" },
    { name = "pointer_target_fixed", type = "Bool" },
    { name = "current_url", type = "String" },
    { name = "type", type = "LowCardinality(String)" },
  ]

  sharded_heatmaps_columns = concat(local.kafka_heatmaps_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])
}

module "sharded_heatmaps_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "heatmaps"
  database = var.database
  columns  = local.sharded_heatmaps_columns
  storage = {
    partition_by = "toYYYYMM(timestamp)"
    order_by     = "(type, team_id, toDate(timestamp), current_url, viewport_width)"
    ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(90)" : null
  }
  sharding_key = "cityHash64(concat(toString(team_id), '-', session_id, '-', toString(toDate(timestamp))))"
  kafka = {
    topic          = "clickhouse_heatmap_events"
    consumer_group = "group1"
    arguments      = "settings"
    columns        = local.kafka_heatmaps_columns
    settings       = {}
  }
  mv_select = <<-SQL
session_id,
    team_id,
    distinct_id,
    timestamp,
    x,
    y,
    scale_factor,
    viewport_width,
    viewport_height,
    pointer_target_fixed,
    current_url,
    type,
    _timestamp,
    _offset,
    _partition
  SQL
  deployment = merge({
    keeper_path      = "/clickhouse/tables/{shard}/${var.database}.heatmaps"
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
  }, local.deployment)
}

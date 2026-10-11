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

module "clickhouse_cleanup_deleted_persons_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "clickhouse_cleanup_deleted_persons"
  database = var.database
  layout   = "global"
  columns = [
    { name = "run_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "person_id", type = "UUID" },
    { name = "max_version", type = "UInt64" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
  ]
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["created_at"]
    partition_by = "run_id"
    order_by     = "(run_id, team_id, person_id)"
    ttl          = var.ttl ? "created_at + toIntervalDay(14)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  deployment = local.deployment
}

module "clickhouse_cleanup_orphaned_distinct_ids_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "clickhouse_cleanup_orphaned_distinct_ids"
  database = var.database
  layout   = "global"
  columns = [
    { name = "run_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "UUID" },
    { name = "own_tombstone", type = "UInt8" },
    { name = "max_version", type = "Int64" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
  ]
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["created_at"]
    partition_by = "run_id"
    order_by     = "(run_id, team_id, distinct_id)"
    ttl          = var.ttl ? "created_at + toIntervalDay(14)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  deployment = local.deployment
}

module "clickhouse_cleanup_revived_distinct_ids_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "clickhouse_cleanup_revived_distinct_ids"
  database = var.database
  layout   = "global"
  columns = [
    { name = "run_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
  ]
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["created_at"]
    partition_by = "run_id"
    order_by     = "(run_id, team_id, distinct_id)"
    ttl          = var.ttl ? "created_at + toIntervalDay(14)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  deployment = local.deployment
}

module "clickhouse_cleanup_revived_persons_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "clickhouse_cleanup_revived_persons"
  database = var.database
  layout   = "global"
  columns = [
    { name = "run_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "person_id", type = "UUID" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
  ]
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["created_at"]
    partition_by = "run_id"
    order_by     = "(run_id, team_id, person_id)"
    ttl          = var.ttl ? "created_at + toIntervalDay(14)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  deployment = local.deployment
}

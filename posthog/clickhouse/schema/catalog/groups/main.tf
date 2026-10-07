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
  kafka_groups_columns = [
    { name = "group_type_index", type = "UInt8" },
    { name = "group_key", type = "String" },
    { name = "created_at", type = "DateTime64(3)" },
    { name = "team_id", type = "Int64" },
    { name = "group_properties", type = "String" },
  ]

  writable_groups_columns = concat(local.kafka_groups_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ])
}

module "groups_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "groups"
  database = var.database
  layout   = "global"
  columns = concat(local.writable_groups_columns, [
    { name = "is_deleted", type = "Bool" },
  ])
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["_timestamp"]
    order_by    = "(team_id, group_type_index, group_key)"
    indexes = [
      { name = "is_deleted_idx", expression = "is_deleted", type = "minmax", granularity = 1 },
    ]
  }
  routing = {
    write_columns = local.writable_groups_columns
  }
  kafka = {
    topic          = "clickhouse_groups"
    consumer_group = "group1"
    arguments      = "settings"
    columns        = local.kafka_groups_columns
    settings       = {}
  }
  mv_select  = <<-SQL
group_type_index,
    group_key,
    created_at,
    team_id,
    group_properties,
    _timestamp,
    _offset
  SQL
  deployment = merge({ kafka_collection = "msk_cluster" }, local.deployment)
}

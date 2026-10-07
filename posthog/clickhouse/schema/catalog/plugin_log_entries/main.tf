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
  kafka_plugin_log_entries_columns = [
    { name = "id", type = "UUID" },
    { name = "team_id", type = "Int64" },
    { name = "plugin_id", type = "Int64" },
    { name = "plugin_config_id", type = "Int64" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "source", type = "String" },
    { name = "type", type = "String" },
    { name = "message", type = "String" },
    { name = "instance_id", type = "UUID" },
  ]

  plugin_log_entries_columns = concat(local.kafka_plugin_log_entries_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ])
}

module "plugin_log_entries_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "plugin_log_entries"
  database = var.database
  layout   = "global"
  columns  = local.plugin_log_entries_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["_timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    order_by     = "(team_id, plugin_id, plugin_config_id, timestamp)"
    ttl          = var.ttl ? "toDate(timestamp) + toIntervalWeek(1)" : null
    settings     = "index_granularity = 512"
  }
  kafka = {
    topic          = "plugin_log_entries"
    consumer_group = "group1"
    arguments      = "settings"
    columns        = local.kafka_plugin_log_entries_columns
    settings       = {}
  }
  mv_select  = <<-SQL
id,
    team_id,
    plugin_id,
    plugin_config_id,
    timestamp,
    source,
    type,
    message,
    instance_id,
    _timestamp,
    _offset
  SQL
  deployment = merge({ kafka_collection = "msk_cluster" }, local.deployment)
}

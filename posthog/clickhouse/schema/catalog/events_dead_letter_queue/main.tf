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
  kafka_events_dead_letter_queue_columns = [
    { name = "id", type = "UUID" },
    { name = "event_uuid", type = "UUID" },
    { name = "event", type = "String" },
    { name = "properties", type = "String" },
    { name = "distinct_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "elements_chain", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')" },
    { name = "ip", type = "String" },
    { name = "site_url", type = "String" },
    { name = "now", type = "DateTime64(6, 'UTC')" },
    { name = "raw_payload", type = "String" },
    { name = "error_timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "error_location", type = "String" },
    { name = "error", type = "String" },
    { name = "tags", type = "Array(String)" },
  ]

  events_dead_letter_queue_columns = concat(local.kafka_events_dead_letter_queue_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ])
}

module "events_dead_letter_queue_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "events_dead_letter_queue"
  database = var.database
  layout   = "global"
  columns  = local.events_dead_letter_queue_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["_timestamp"]
    order_by    = "(id, event_uuid, distinct_id, team_id)"
    ttl         = var.ttl ? "toDate(_timestamp) + toIntervalWeek(4)" : null
    settings    = "index_granularity = 512"
    indexes = [
      { name = "kafka_timestamp_minmax_events_dead_letter_queue", expression = "_timestamp", type = "minmax", granularity = 3 },
    ]
  }
  kafka = {
    topic          = "events_dead_letter_queue"
    consumer_group = "group1"
    arguments      = "settings"
    columns        = local.kafka_events_dead_letter_queue_columns
    settings       = { kafka_skip_broken_messages = "1000" }
  }
  mv_select  = <<-SQL
id,
    event_uuid,
    event,
    properties,
    distinct_id,
    team_id,
    elements_chain,
    created_at,
    ip,
    site_url,
    now,
    raw_payload,
    error_timestamp,
    error_location,
    error,
    tags,
    _timestamp,
    _offset
  SQL
  deployment = merge({ kafka_collection = "msk_cluster" }, local.deployment)
}

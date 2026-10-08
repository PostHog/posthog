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
  kafka_message_assets_columns = [
    { name = "team_id", type = "Int64" },
    { name = "function_kind", type = "LowCardinality(String)" },
    { name = "function_id", type = "String" },
    { name = "parent_run_id", type = "String" },
    { name = "invocation_id", type = "String" },
    { name = "action_id", type = "String" },
    { name = "kind", type = "LowCardinality(String)" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "String" },
    { name = "recipient", type = "String" },
    { name = "subject", type = "String" },
    { name = "status", type = "LowCardinality(String)" },
    { name = "sent_at", type = "DateTime64(6, 'UTC')" },
    { name = "version", type = "UInt64" },
    { name = "is_deleted", type = "UInt8" },
    { name = "html", type = "String" },
  ]
}

module "message_assets_data_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "message_assets"
  database = var.database
  layout   = "global"
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "function_kind", type = "LowCardinality(String)" },
    { name = "function_id", type = "String" },
    { name = "parent_run_id", type = "String" },
    { name = "invocation_id", type = "String" },
    { name = "action_id", type = "String" },
    { name = "kind", type = "LowCardinality(String)" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "String" },
    { name = "recipient", type = "String" },
    { name = "subject", type = "String" },
    { name = "status", type = "LowCardinality(String)" },
    { name = "sent_at", type = "DateTime64(6, 'UTC')" },
    { name = "version", type = "UInt64" },
    { name = "is_deleted", type = "UInt8", default_expression = "0" },
    { name = "html", type = "String", codec = "ZSTD(3)" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["version"]
    partition_by = "toYYYYMMDD(sent_at)"
    order_by     = "(team_id, function_kind, function_id, invocation_id, action_id)"
    ttl          = var.ttl ? "toDate(sent_at) + toIntervalDay(30)" : null
    settings     = "index_granularity = 1024, ttl_only_drop_parts = 1"
    indexes = [
      { name = "parent_run_idx", expression = "parent_run_id", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "distinct_id_idx", expression = "distinct_id", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "person_id_idx", expression = "person_id", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "recipient_idx", expression = "recipient", type = "bloom_filter(0.01)", granularity = 1 },
    ]
  }
  routing = {
    read  = true
    write = false
    read_columns = concat(local.kafka_message_assets_columns, [
      { name = "_timestamp", type = "DateTime" },
      { name = "_offset", type = "UInt64" },
      { name = "_partition", type = "UInt64" },
    ])
  }
  kafka = {
    topic     = "clickhouse_message_assets"
    arguments = "settings"
    columns   = local.kafka_message_assets_columns
    settings  = { kafka_skip_broken_messages = "100" }
  }
  mv_select  = <<-SQL
team_id,
    function_kind,
    function_id,
    parent_run_id,
    invocation_id,
    action_id,
    kind,
    distinct_id,
    person_id,
    recipient,
    subject,
    status,
    sent_at,
    version,
    is_deleted,
    html,
    _timestamp,
    _offset,
    _partition
  SQL
  mv_target  = "${var.database}.message_assets_data"
  deployment = merge({ cluster = "aux", kafka_collection = "warpstream_cyclotron" }, local.deployment)
  names      = { storage = "message_assets_data" }
}

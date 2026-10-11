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
  kafka_hog_invocation_results_columns = [
    { name = "team_id", type = "Int64" },
    { name = "function_kind", type = "LowCardinality(String)" },
    { name = "function_id", type = "String" },
    { name = "invocation_id", type = "String" },
    { name = "parent_run_id", type = "String" },
    { name = "status", type = "LowCardinality(String)" },
    { name = "attempts", type = "UInt8" },
    { name = "is_retry", type = "UInt8" },
    { name = "scheduled_at", type = "DateTime64(6, 'UTC')" },
    { name = "first_scheduled_at", type = "DateTime64(6, 'UTC')" },
    { name = "started_at", type = "Nullable(DateTime64(6, 'UTC'))" },
    { name = "finished_at", type = "Nullable(DateTime64(6, 'UTC'))" },
    { name = "duration_ms", type = "Nullable(UInt32)" },
    { name = "error_kind", type = "LowCardinality(String)" },
    { name = "error_message", type = "String" },
    { name = "event_uuid", type = "String" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "String" },
    { name = "invocation_globals", type = "String" },
    { name = "version", type = "UInt64" },
    { name = "is_deleted", type = "UInt8" },
  ]
}

module "hog_invocation_results_data_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "hog_invocation_results"
  database = var.database
  layout   = "global"
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "function_kind", type = "LowCardinality(String)" },
    { name = "function_id", type = "String" },
    { name = "invocation_id", type = "String" },
    { name = "parent_run_id", type = "String" },
    { name = "status", type = "LowCardinality(String)" },
    { name = "attempts", type = "UInt8" },
    { name = "is_retry", type = "UInt8" },
    { name = "scheduled_at", type = "DateTime64(6, 'UTC')" },
    { name = "first_scheduled_at", type = "DateTime64(6, 'UTC')", default_expression = "scheduled_at" },
    { name = "started_at", type = "Nullable(DateTime64(6, 'UTC'))" },
    { name = "finished_at", type = "Nullable(DateTime64(6, 'UTC'))" },
    { name = "duration_ms", type = "Nullable(UInt32)" },
    { name = "error_kind", type = "LowCardinality(String)" },
    { name = "error_message", type = "String" },
    { name = "event_uuid", type = "String" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "String" },
    { name = "invocation_globals", type = "String" },
    { name = "version", type = "UInt64" },
    { name = "is_deleted", type = "UInt8", default_expression = "0" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["version"]
    partition_by = "toYYYYMMDD(scheduled_at)"
    order_by     = "(team_id, function_kind, function_id, invocation_id)"
    ttl          = var.ttl ? "toDate(scheduled_at) + toIntervalDay(30)" : null
    settings     = "index_granularity = 1024, ttl_only_drop_parts = 1"
    indexes = [
      { name = "status_idx", expression = "status", type = "set(8)", granularity = 1 },
      { name = "function_idx", expression = "function_id", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "event_uuid_idx", expression = "event_uuid", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "is_retry_idx", expression = "is_retry", type = "set(2)", granularity = 1 },
    ]
  }
  routing = {
    read  = true
    write = false
    read_columns = concat(local.kafka_hog_invocation_results_columns, [
      { name = "_timestamp", type = "DateTime" },
      { name = "_offset", type = "UInt64" },
      { name = "_partition", type = "UInt64" },
    ])
  }
  kafka = {
    topic     = "clickhouse_hog_invocation_results"
    arguments = "settings"
    columns   = local.kafka_hog_invocation_results_columns
    settings  = { kafka_skip_broken_messages = "100" }
  }
  mv_select  = <<-SQL
team_id,
    function_kind,
    function_id,
    invocation_id,
    parent_run_id,
    status,
    attempts,
    is_retry,
    scheduled_at,
    if(first_scheduled_at = toDateTime64('1970-01-01 00:00:00', 6, 'UTC'), scheduled_at, first_scheduled_at) AS first_scheduled_at,
    started_at,
    finished_at,
    duration_ms,
    error_kind,
    error_message,
    event_uuid,
    distinct_id,
    person_id,
    invocation_globals,
    version,
    is_deleted,
    _timestamp,
    _offset,
    _partition
  SQL
  mv_target  = "${var.database}.hog_invocation_results_data"
  deployment = merge({ cluster = "aux", kafka_collection = "warpstream_cyclotron" }, local.deployment)
  names      = { storage = "hog_invocation_results_data" }
}

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

locals {
}

# Column lists that more than one object uses.

locals {
  sharded_ai_events_columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "LowCardinality(String)" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "UUID" },
    { name = "properties", type = "String" },
    { name = "retention_days", type = "Int16", default_expression = "30" },
    { name = "drop_date", type = "Date", materialized_expression = "toDate(timestamp) + toIntervalDay(retention_days)" },
    { name = "trace_id", type = "String" },
    { name = "session_id", type = "Nullable(String)" },
    { name = "parent_id", type = "Nullable(String)" },
    { name = "span_id", type = "Nullable(String)" },
    { name = "span_type", type = "LowCardinality(Nullable(String))" },
    { name = "generation_id", type = "Nullable(String)" },
    { name = "experiment_id", type = "Nullable(String)" },
    { name = "span_name", type = "Nullable(String)" },
    { name = "trace_name", type = "Nullable(String)" },
    { name = "prompt_name", type = "Nullable(String)" },
    { name = "model", type = "LowCardinality(Nullable(String))" },
    { name = "provider", type = "LowCardinality(Nullable(String))" },
    { name = "framework", type = "LowCardinality(Nullable(String))" },
    { name = "total_tokens", type = "Nullable(Int64)" },
    { name = "input_tokens", type = "Nullable(Int64)" },
    { name = "output_tokens", type = "Nullable(Int64)" },
    { name = "text_input_tokens", type = "Nullable(Int64)" },
    { name = "text_output_tokens", type = "Nullable(Int64)" },
    { name = "image_input_tokens", type = "Nullable(Int64)" },
    { name = "image_output_tokens", type = "Nullable(Int64)" },
    { name = "audio_input_tokens", type = "Nullable(Int64)" },
    { name = "audio_output_tokens", type = "Nullable(Int64)" },
    { name = "video_input_tokens", type = "Nullable(Int64)" },
    { name = "video_output_tokens", type = "Nullable(Int64)" },
    { name = "reasoning_tokens", type = "Nullable(Int64)" },
    { name = "cache_read_input_tokens", type = "Nullable(Int64)" },
    { name = "cache_creation_input_tokens", type = "Nullable(Int64)" },
    { name = "web_search_count", type = "Nullable(Int64)" },
    { name = "input_cost_usd", type = "Nullable(Float64)" },
    { name = "output_cost_usd", type = "Nullable(Float64)" },
    { name = "total_cost_usd", type = "Nullable(Float64)" },
    { name = "request_cost_usd", type = "Nullable(Float64)" },
    { name = "web_search_cost_usd", type = "Nullable(Float64)" },
    { name = "audio_cost_usd", type = "Nullable(Float64)" },
    { name = "image_cost_usd", type = "Nullable(Float64)" },
    { name = "video_cost_usd", type = "Nullable(Float64)" },
    { name = "latency", type = "Nullable(Float64)" },
    { name = "time_to_first_token", type = "Nullable(Float64)" },
    { name = "is_error", type = "UInt8" },
    { name = "error", type = "Nullable(String)" },
    { name = "error_type", type = "LowCardinality(Nullable(String))" },
    { name = "error_normalized", type = "Nullable(String)" },
    { name = "input", type = "Nullable(String)" },
    { name = "output", type = "Nullable(String)" },
    { name = "output_choices", type = "Nullable(String)" },
    { name = "input_state", type = "Nullable(String)" },
    { name = "output_state", type = "Nullable(String)" },
    { name = "tools", type = "Nullable(String)" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
}

module "sharded_ai_events_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "ai_events"
  database = var.database
  columns  = local.sharded_ai_events_columns
  storage = {
    partition_by = "toYYYYMM(drop_date)"
    order_by     = "(team_id, trace_id, timestamp)"
    ttl          = var.ttl ? "drop_date" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
    indexes = [
      { name = "idx_trace_id", expression = "trace_id", type = "bloom_filter(0.001)", granularity = 1 },
      { name = "idx_session_id", expression = "session_id", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_parent_id", expression = "parent_id", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_span_id", expression = "span_id", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_prompt_name", expression = "prompt_name", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_model", expression = "model", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_experiment_id", expression = "experiment_id", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_event", expression = "event", type = "set(20)", granularity = 1 },
      { name = "idx_is_error", expression = "is_error", type = "set(2)", granularity = 1 },
      { name = "idx_provider", expression = "provider", type = "set(50)", granularity = 1 },
    ]
  }
  routing = {
    write        = false
    read_columns = local.sharded_ai_events_columns
  }
  sharding_key = "cityHash64(concat(toString(team_id), '-', trace_id, '-', toString(toDate(timestamp))))"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.ai_events"
    cluster     = "ai_events"
  }, local.deployment)
}

# Kafka tables and the materialized views that consume them.

module "ai_events_json_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "ai_events_json_mv")
  database = var.database
  name     = "ai_events_json_mv"
  to_table = "${var.database}.ai_events"
  query    = <<-SQL
    SELECT
        uuid,
        event,
        timestamp,
        team_id,
        distinct_id,
        person_id,
        concat('{', arrayStringConcat(arrayMap(x -> concat('"', x.1, '":', x.2), arrayFilter(x -> ((x.1) NOT IN ('$ai_input', '$ai_output', '$ai_output_choices', '$ai_input_state', '$ai_output_state', '$ai_tools')), JSONExtractKeysAndValuesRaw(src.properties))), ','), '}') AS properties,
        JSONExtractString(src.properties, '$ai_trace_id') AS trace_id,
        JSONExtract(src.properties, '$ai_session_id', 'Nullable(String)') AS session_id,
        JSONExtract(src.properties, '$ai_parent_id', 'Nullable(String)') AS parent_id,
        JSONExtract(src.properties, '$ai_span_id', 'Nullable(String)') AS span_id,
        JSONExtract(src.properties, '$ai_span_type', 'Nullable(String)') AS span_type,
        JSONExtract(src.properties, '$ai_generation_id', 'Nullable(String)') AS generation_id,
        JSONExtract(src.properties, '$ai_experiment_id', 'Nullable(String)') AS experiment_id,
        JSONExtract(src.properties, '$ai_span_name', 'Nullable(String)') AS span_name,
        JSONExtract(src.properties, '$ai_trace_name', 'Nullable(String)') AS trace_name,
        JSONExtract(src.properties, '$ai_prompt_name', 'Nullable(String)') AS prompt_name,
        JSONExtract(src.properties, '$ai_model', 'Nullable(String)') AS model,
        JSONExtract(src.properties, '$ai_provider', 'Nullable(String)') AS provider,
        JSONExtract(src.properties, '$ai_framework', 'Nullable(String)') AS framework,
        JSONExtract(src.properties, '$ai_total_tokens', 'Nullable(Int64)') AS total_tokens,
        JSONExtract(src.properties, '$ai_input_tokens', 'Nullable(Int64)') AS input_tokens,
        JSONExtract(src.properties, '$ai_output_tokens', 'Nullable(Int64)') AS output_tokens,
        JSONExtract(src.properties, '$ai_text_input_tokens', 'Nullable(Int64)') AS text_input_tokens,
        JSONExtract(src.properties, '$ai_text_output_tokens', 'Nullable(Int64)') AS text_output_tokens,
        JSONExtract(src.properties, '$ai_image_input_tokens', 'Nullable(Int64)') AS image_input_tokens,
        JSONExtract(src.properties, '$ai_image_output_tokens', 'Nullable(Int64)') AS image_output_tokens,
        JSONExtract(src.properties, '$ai_audio_input_tokens', 'Nullable(Int64)') AS audio_input_tokens,
        JSONExtract(src.properties, '$ai_audio_output_tokens', 'Nullable(Int64)') AS audio_output_tokens,
        JSONExtract(src.properties, '$ai_video_input_tokens', 'Nullable(Int64)') AS video_input_tokens,
        JSONExtract(src.properties, '$ai_video_output_tokens', 'Nullable(Int64)') AS video_output_tokens,
        JSONExtract(src.properties, '$ai_reasoning_tokens', 'Nullable(Int64)') AS reasoning_tokens,
        JSONExtract(src.properties, '$ai_cache_read_input_tokens', 'Nullable(Int64)') AS cache_read_input_tokens,
        JSONExtract(src.properties, '$ai_cache_creation_input_tokens', 'Nullable(Int64)') AS cache_creation_input_tokens,
        JSONExtract(src.properties, '$ai_web_search_count', 'Nullable(Int64)') AS web_search_count,
        JSONExtract(src.properties, '$ai_input_cost_usd', 'Nullable(Float64)') AS input_cost_usd,
        JSONExtract(src.properties, '$ai_output_cost_usd', 'Nullable(Float64)') AS output_cost_usd,
        JSONExtract(src.properties, '$ai_total_cost_usd', 'Nullable(Float64)') AS total_cost_usd,
        JSONExtract(src.properties, '$ai_request_cost_usd', 'Nullable(Float64)') AS request_cost_usd,
        JSONExtract(src.properties, '$ai_web_search_cost_usd', 'Nullable(Float64)') AS web_search_cost_usd,
        JSONExtract(src.properties, '$ai_audio_cost_usd', 'Nullable(Float64)') AS audio_cost_usd,
        JSONExtract(src.properties, '$ai_image_cost_usd', 'Nullable(Float64)') AS image_cost_usd,
        JSONExtract(src.properties, '$ai_video_cost_usd', 'Nullable(Float64)') AS video_cost_usd,
        JSONExtract(src.properties, '$ai_latency', 'Nullable(Float64)') AS latency,
        JSONExtract(src.properties, '$ai_time_to_first_token', 'Nullable(Float64)') AS time_to_first_token,
        if((JSONExtractRaw(src.properties, '$ai_is_error') IN ('true', '"true"')), 1, 0) AS is_error,
        JSONExtract(src.properties, '$ai_error', 'Nullable(String)') AS error,
        JSONExtract(src.properties, '$ai_error_type', 'Nullable(String)') AS error_type,
        JSONExtract(src.properties, '$ai_error_normalized', 'Nullable(String)') AS error_normalized,
        nullIf(JSONExtractRaw(src.properties, '$ai_input'), '') AS input,
        nullIf(JSONExtractRaw(src.properties, '$ai_output'), '') AS output,
        nullIf(JSONExtractRaw(src.properties, '$ai_output_choices'), '') AS output_choices,
        nullIf(JSONExtractRaw(src.properties, '$ai_input_state'), '') AS input_state,
        nullIf(JSONExtractRaw(src.properties, '$ai_output_state'), '') AS output_state,
        nullIf(JSONExtractRaw(src.properties, '$ai_tools'), '') AS tools,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_ai_events_json AS src
  SQL
  override = try(local.deployment.overrides["ai_events_json_mv"], {})

  depends_on = [
    module.sharded_ai_events_family,
    module.kafka_ai_events_json,
  ]
}

module "kafka_ai_events_json" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_ai_events_json")
  database = var.database
  name     = "kafka_ai_events_json"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'clickhouse_ai_events_json'"
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "String" },
    { name = "properties", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "elements_chain", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')" },
    { name = "person_id", type = "UUID" },
    { name = "person_properties", type = "String" },
    { name = "person_created_at", type = "DateTime64(3)" },
    { name = "person_mode", type = "Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)" },
  ]
  override = try(local.deployment.overrides["kafka_ai_events_json"], {})
}

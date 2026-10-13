# Production objects from before this catalogue, declared from their live definitions. Only Cloud roots
# in posthog-cloud-infra list them.

variable "node" {
  type    = any
  default = null
}

variable "database" {
  type    = string
  default = "posthog"
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

module "ai_events_merge" {
  source = "../../lib/table"
  node   = var.node

  enabled      = contains(var.objects, "ai_events_merge")
  database     = var.database
  name         = "ai_events_merge"
  override     = try(local.deployment.overrides["ai_events_merge"], {})
  engine       = "ReplicatedMergeTree('/clickhouse/ai_events/tables/{shard}/posthog.ai_events', '{replica}')"
  partition_by = "toYYYYMM(drop_date)"
  order_by     = "(team_id, trace_id, timestamp)"
  ttl          = "drop_date"
  settings     = "ttl_only_drop_parts = 1, index_granularity = 8192"
  columns = [
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
  indexes = [
    { name = "idx_event", expression = "event", type = "set(20)", granularity = 1 },
    { name = "idx_experiment_id", expression = "experiment_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_is_error", expression = "is_error", type = "set(2)", granularity = 1 },
    { name = "idx_model", expression = "model", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_parent_id", expression = "parent_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_prompt_name", expression = "prompt_name", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_provider", expression = "provider", type = "set(50)", granularity = 1 },
    { name = "idx_session_id", expression = "session_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_span_id", expression = "span_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_trace_id", expression = "trace_id", type = "bloom_filter(0.001)", granularity = 1 },
  ]
}

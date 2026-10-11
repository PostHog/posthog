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

module "sharded_flag_evaluations_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "flag_evaluations"
  database = var.database
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "LowCardinality(String)" },
    { name = "properties", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')" },
    { name = "person_id", type = "UUID" },
    { name = "inserted_at", type = "DateTime64(6, 'UTC')", default_expression = "timestamp" },
    { name = "$group_0", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), '^\"|\"$', '')", comment = "column_materializer::$group_0" },
    { name = "$group_1", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$group_1'), '^\"|\"$', '')", comment = "column_materializer::$group_1" },
    { name = "$group_2", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$group_2'), '^\"|\"$', '')", comment = "column_materializer::$group_2" },
    { name = "$group_3", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$group_3'), '^\"|\"$', '')", comment = "column_materializer::$group_3" },
    { name = "$group_4", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$group_4'), '^\"|\"$', '')", comment = "column_materializer::$group_4" },
    { name = "flag_key", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag'), '^\"|\"$', '')", comment = "column_materializer::properties::$feature_flag" },
    { name = "response", type = "LowCardinality(String)", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag_response'), '^\"|\"$', '')", comment = "column_materializer::properties::$feature_flag_response" },
    { name = "session_id", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$session_id'), '^\"|\"$', '')", comment = "column_materializer::properties::$session_id" },
    { name = "request_id", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag_request_id'), '^\"|\"$', '')", comment = "column_materializer::properties::$feature_flag_request_id" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
  storage = {
    partition_by = "toYYYYMM(timestamp)"
    order_by     = "(team_id, flag_key, toDate(timestamp), cityHash64(distinct_id))"
    ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(90)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
    indexes = [
      { name = "distinct_id_idx", expression = "distinct_id", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "person_id_idx", expression = "person_id", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "session_id_idx", expression = "session_id", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "request_id_idx", expression = "request_id", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "inserted_at_idx", expression = "inserted_at", type = "minmax", granularity = 1 },
    ]
  }
  routing = {
    read_columns = [
      { name = "uuid", type = "UUID" },
      { name = "event", type = "LowCardinality(String)" },
      { name = "properties", type = "String" },
      { name = "timestamp", type = "DateTime64(6, 'UTC')" },
      { name = "team_id", type = "Int64" },
      { name = "distinct_id", type = "String" },
      { name = "created_at", type = "DateTime64(6, 'UTC')" },
      { name = "person_id", type = "UUID" },
      { name = "inserted_at", type = "DateTime64(6, 'UTC')", default_expression = "timestamp" },
      { name = "$group_0", type = "String", comment = "column_materializer::$group_0" },
      { name = "$group_1", type = "String", comment = "column_materializer::$group_1" },
      { name = "$group_2", type = "String", comment = "column_materializer::$group_2" },
      { name = "$group_3", type = "String", comment = "column_materializer::$group_3" },
      { name = "$group_4", type = "String", comment = "column_materializer::$group_4" },
      { name = "flag_key", type = "String", comment = "column_materializer::properties::$feature_flag" },
      { name = "response", type = "LowCardinality(String)", comment = "column_materializer::properties::$feature_flag_response" },
      { name = "session_id", type = "String", comment = "column_materializer::properties::$session_id" },
      { name = "request_id", type = "String", comment = "column_materializer::properties::$feature_flag_request_id" },
      { name = "_timestamp", type = "DateTime" },
      { name = "_offset", type = "UInt64" },
      { name = "_partition", type = "UInt64" },
    ]
    write_columns = [
      { name = "uuid", type = "UUID" },
      { name = "event", type = "LowCardinality(String)" },
      { name = "properties", type = "String" },
      { name = "timestamp", type = "DateTime64(6, 'UTC')" },
      { name = "team_id", type = "Int64" },
      { name = "distinct_id", type = "String" },
      { name = "created_at", type = "DateTime64(6, 'UTC')" },
      { name = "person_id", type = "UUID" },
      { name = "inserted_at", type = "DateTime64(6, 'UTC')", default_expression = "timestamp" },
      { name = "_timestamp", type = "DateTime" },
      { name = "_offset", type = "UInt64" },
      { name = "_partition", type = "UInt64" },
    ]
  }
  sharding_key = "sipHash64(distinct_id)"
  kafka = {
    topic     = "clickhouse_flag_evaluations"
    arguments = "settings"
    columns = [
      { name = "uuid", type = "UUID" },
      { name = "event", type = "LowCardinality(String)" },
      { name = "properties", type = "String" },
      { name = "timestamp", type = "DateTime64(6, 'UTC')" },
      { name = "team_id", type = "Int64" },
      { name = "distinct_id", type = "String" },
      { name = "created_at", type = "DateTime64(6, 'UTC')" },
      { name = "person_id", type = "UUID" },
      { name = "inserted_at", type = "DateTime64(6, 'UTC')" },
    ]
    settings = { kafka_flush_interval_ms = "7500", kafka_max_block_size = "10000", kafka_num_consumers = "1", kafka_poll_max_batch_size = "10000", kafka_poll_timeout_ms = "10000", kafka_skip_broken_messages = "100" }
  }
  mv_select = <<-SQL
uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    created_at,
    person_id,
    if(inserted_at = toDateTime64('1970-01-01 00:00:00', 6, 'UTC'), _timestamp, inserted_at) AS inserted_at,
    _timestamp,
    _offset,
    _partition
  SQL
  deployment = merge({
    keeper_path      = "/clickhouse/tables/{shard}/${var.database}.flag_evaluations"
    cluster          = "posthog"
    kafka_collection = "warpstream_ingestion"
  }, local.deployment)
}

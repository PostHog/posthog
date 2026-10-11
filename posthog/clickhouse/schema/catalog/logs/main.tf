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
  test = var.test
}

# Column lists that more than one object uses.

locals {
  logs_billing_metrics_columns = [
    { name = "team_id", type = "Int32" },
    { name = "time_bucket", type = "DateTime64(0)" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "bytes_uncompressed", type = "SimpleAggregateFunction(sum, UInt64)" },
    { name = "bytes_compressed", type = "SimpleAggregateFunction(sum, UInt64)" },
    { name = "record_count", type = "SimpleAggregateFunction(sum, UInt64)" },
  ]

  logs_kafka_metrics_columns = [
    { name = "_partition", type = "UInt32" },
    { name = "_topic", type = "String" },
    { name = "max_offset", type = "SimpleAggregateFunction(max, UInt64)" },
    { name = "max_observed_timestamp", type = "SimpleAggregateFunction(max, DateTime64(9))" },
    { name = "max_timestamp", type = "SimpleAggregateFunction(max, DateTime64(9))" },
    { name = "max_created_at", type = "SimpleAggregateFunction(max, DateTime64(9))" },
    { name = "max_lag", type = "SimpleAggregateFunction(max, UInt64)" },
  ]

  logs_volume_buckets_columns = [
    { name = "team_id", type = "Int32" },
    { name = "time_bucket", type = "DateTime('UTC')", codec = "DoubleDelta, ZSTD(1)" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "namespace", type = "LowCardinality(String)" },
    { name = "environment", type = "LowCardinality(String)" },
    { name = "severity_text", type = "LowCardinality(String)" },
    { name = "retention_days", type = "SimpleAggregateFunction(max, UInt16)" },
    { name = "log_count", type = "SimpleAggregateFunction(sum, UInt64)" },
  ]

  log_attributes2_columns = [
    { name = "team_id", type = "Int32" },
    { name = "time_bucket", type = "DateTime64(0)" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "resource_fingerprint", type = "UInt64", default_expression = "0" },
    { name = "attribute_key", type = "LowCardinality(String)" },
    { name = "attribute_value", type = "String", codec = "ZSTD(5)" },
    { name = "attribute_count", type = "SimpleAggregateFunction(sum, UInt64)" },
    { name = "attribute_type", type = "LowCardinality(String)", default_expression = "'log'" },
    { name = "original_expiry_time_bucket", type = "DateTime", default_expression = "now()" },
  ]

  logs_pattern_buckets_columns = [
    { name = "team_id", type = "Int32" },
    { name = "time_bucket", type = "DateTime('UTC')", codec = "DoubleDelta, ZSTD(1)" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "namespace", type = "LowCardinality(String)" },
    { name = "environment", type = "LowCardinality(String)" },
    { name = "severity_text", type = "LowCardinality(String)" },
    { name = "pattern_version", type = "UInt8" },
    { name = "pattern", type = "String" },
    { name = "log_count", type = "SimpleAggregateFunction(sum, UInt64)" },
  ]

  log_attributes3_columns = concat(local.log_attributes2_columns, [
    { name = "severity_text", type = "LowCardinality(String)" },
  ])

  logs32_columns = [
    { name = "time_bucket", type = "DateTime", materialized_expression = "toStartOfDay(timestamp)", codec = "DoubleDelta, ZSTD(1)" },
    { name = "original_expiry_timestamp", type = "DateTime64(6)", codec = "DoubleDelta, ZSTD(1)" },
    { name = "uuid", type = "String", codec = "ZSTD(1)" },
    { name = "team_id", type = "Int32", codec = "ZSTD(1)" },
    { name = "trace_id", type = "String", codec = "ZSTD(1)" },
    { name = "span_id", type = "String", codec = "ZSTD(1)" },
    { name = "trace_flags", type = "Int32", codec = "ZSTD(1)" },
    { name = "timestamp", type = "DateTime64(6)", codec = "DoubleDelta, ZSTD(1)" },
    { name = "observed_timestamp", type = "DateTime64(6)", codec = "DoubleDelta, ZSTD(1)" },
    { name = "created_at", type = "DateTime64(6)", materialized_expression = "now()", codec = "DoubleDelta, ZSTD(1)" },
    { name = "body", type = "String", codec = "ZSTD(1)" },
    { name = "severity_text", type = "LowCardinality(String)", codec = "ZSTD(1)" },
    { name = "severity_number", type = "Int32", codec = "ZSTD(1)" },
    { name = "service_name", type = "LowCardinality(String)", codec = "ZSTD(1)" },
    { name = "resource_attributes", type = "Map(LowCardinality(String), String)", codec = "ZSTD(1)" },
    { name = "resource_fingerprint", type = "UInt64", materialized_expression = "cityHash64(resource_attributes)", codec = "DoubleDelta, ZSTD(1)" },
    { name = "instrumentation_scope", type = "String", codec = "ZSTD(1)" },
    { name = "event_name", type = "String", codec = "ZSTD(1)" },
    { name = "attributes_map_str", type = "Map(LowCardinality(String), String)", codec = "ZSTD(1)" },
    { name = "level", type = "String", alias_expression = "severity_text" },
    { name = "mat_body_ipv4_matches", type = "Array(String)", alias_expression = "extractAll(body, '(\\\\d\\\\.((25[0-5]|(2[0-4]|1(0, 1)[0-9])(0, 1)[0-9])\\\\.)(2, 2)([0-9]))')" },
    { name = "time_minute", type = "DateTime", alias_expression = "toStartOfMinute(timestamp)" },
    { name = "attributes", type = "Map(LowCardinality(String), String)", alias_expression = "mapApply((k, v) -> (left(k, -5), v), attributes_map_str)" },
    { name = "attributes_map_float", type = "Map(LowCardinality(String), Float64)", materialized_expression = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str))", codec = "ZSTD(1)" },
    { name = "attributes_map_datetime", type = "Map(LowCardinality(String), DateTime64(6))", materialized_expression = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str))", codec = "ZSTD(1)" },
    { name = "_partition", type = "UInt32", codec = "DoubleDelta, ZSTD(1)" },
    { name = "_topic", type = "String" },
    { name = "_offset", type = "UInt64", codec = "DoubleDelta, ZSTD(1)" },
    { name = "_bytes_uncompressed", type = "UInt64", codec = "DoubleDelta, ZSTD(1)" },
    { name = "_bytes_compressed", type = "UInt64", codec = "DoubleDelta, ZSTD(1)" },
    { name = "_record_count", type = "UInt64", codec = "DoubleDelta, ZSTD(1)" },
    { name = "pattern", type = "String" },
    { name = "pattern_version", type = "UInt8" },
  ]

  logs34_columns = [
    { name = "time_bucket", type = "DateTime", materialized_expression = "toStartOfDay(timestamp)" },
    { name = "original_expiry_timestamp", type = "DateTime64(6)" },
    { name = "uuid", type = "String" },
    { name = "team_id", type = "Int32" },
    { name = "trace_id", type = "String" },
    { name = "span_id", type = "String" },
    { name = "trace_flags", type = "Int32" },
    { name = "timestamp", type = "DateTime64(6)", codec = "DoubleDelta" },
    { name = "observed_timestamp", type = "DateTime64(6)" },
    { name = "created_at", type = "DateTime64(6)", materialized_expression = "now()" },
    { name = "body", type = "String" },
    { name = "severity_text", type = "LowCardinality(String)" },
    { name = "severity_number", type = "Int32" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "resource_attributes", type = "Map(LowCardinality(String), String)" },
    { name = "resource_fingerprint", type = "UInt64", materialized_expression = "cityHash64(resource_attributes)" },
    { name = "instrumentation_scope", type = "String" },
    { name = "event_name", type = "String" },
    { name = "attributes_map_str", type = "Map(LowCardinality(String), String)" },
    { name = "level", type = "String", alias_expression = "severity_text" },
    { name = "mat_body_ipv4_matches", type = "Array(String)", alias_expression = "extractAll(body, '(\\\\d\\\\.((25[0-5]|(2[0-4]|1(0, 1)[0-9])(0, 1)[0-9])\\\\.)(2, 2)([0-9]))')" },
    { name = "time_minute", type = "DateTime", alias_expression = "toStartOfMinute(timestamp)" },
    { name = "attributes", type = "Map(LowCardinality(String), String)", alias_expression = "mapApply((k, v) -> (left(k, -5), v), attributes_map_str)" },
    { name = "attributes_map_float", type = "Map(LowCardinality(String), Float64)", materialized_expression = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str))" },
    { name = "attributes_map_datetime", type = "Map(LowCardinality(String), DateTime64(6))", materialized_expression = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str))" },
    { name = "_partition", type = "UInt32" },
    { name = "_topic", type = "String" },
    { name = "_offset", type = "UInt64" },
    { name = "_bytes_uncompressed", type = "UInt64" },
    { name = "_bytes_compressed", type = "UInt64" },
    { name = "_record_count", type = "UInt64" },
    { name = "pattern", type = "String" },
    { name = "pattern_version", type = "UInt8" },
  ]
}

module "log_attributes_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "log_attributes"
  database = var.database
  layout   = "global"
  columns = [
    { name = "team_id", type = "Int32", codec = "DoubleDelta, ZSTD(1)" },
    { name = "time_bucket", type = "DateTime64(0)", codec = "DoubleDelta, ZSTD(1)" },
    { name = "original_expiry_time_bucket", type = "DateTime64(0)", codec = "DoubleDelta, ZSTD(1)" },
    { name = "service_name", type = "LowCardinality(String)", codec = "ZSTD(1)" },
    { name = "resource_fingerprint", type = "UInt64", default_expression = "0", codec = "DoubleDelta, ZSTD(1)" },
    { name = "attribute_key", type = "LowCardinality(String)", codec = "ZSTD(1)" },
    { name = "attribute_value", type = "String", codec = "ZSTD(1)" },
    { name = "attribute_count", type = "SimpleAggregateFunction(sum, UInt64)" },
    { name = "attribute_type", type = "LowCardinality(String)" },
  ]
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toDate(original_expiry_time_bucket)"
    order_by     = "(team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)"
    settings     = "deduplicate_merge_projection_mode = 'drop', index_granularity = 8192, storage_policy = 'default'"
    indexes = [
      { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
      { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
    ]
  }
  deployment = local.deployment
}

module "log_attributes2_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "log_attributes2"
  database = var.database
  layout   = "global"
  columns  = local.log_attributes2_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toDate(original_expiry_time_bucket)"
    order_by     = "(team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)"
    ttl          = var.ttl ? "original_expiry_time_bucket" : null
    settings     = "deduplicate_merge_projection_mode = 'drop', index_granularity = 8192"
    indexes = [
      { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
      { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
    ]
  }
  deployment = local.deployment
}

module "log_attributes3_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "log_attributes_distributed"
  database = var.database
  layout   = "global"
  columns  = local.log_attributes3_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toDate(original_expiry_time_bucket)"
    order_by     = "(team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value, severity_text)"
    ttl          = var.ttl ? "original_expiry_time_bucket" : null
    settings     = "deduplicate_merge_projection_mode = 'drop', index_granularity = 8192"
    indexes = [
      { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
      { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
    ]
  }
  routing = {
    read         = true
    read_columns = local.log_attributes3_columns
  }
  deployment = merge({ read_cluster = "posthog_single_shard" }, local.deployment)
  names      = { storage = "log_attributes3" }
}

module "logs32_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "logs"
  database = var.database
  layout   = "global"
  columns  = local.logs32_columns
  storage = {
    partition_by = "toDate(original_expiry_timestamp)"
    order_by     = "(team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp)"
    settings     = "add_minmax_index_for_numeric_columns = 1, allow_experimental_reverse_key = 1, allow_remote_fs_zero_copy_replication = 1, index_granularity = 8192, index_granularity_bytes = 104857600, storage_policy = 'default', ttl_only_drop_parts = 1"
    indexes = [
      { name = "idx_severity_text_set", expression = "severity_text", type = "set(10)", granularity = 1 },
      { name = "idx_attributes_str_keys", expression = "mapKeys(attributes_map_str)", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attributes_str_values", expression = "mapValues(attributes_map_str)", type = "bloom_filter(0.001)", granularity = 1 },
      { name = "idx_mat_body_ipv4_matches", expression = "mat_body_ipv4_matches", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_body_ngram3", expression = "lower(body)", type = "ngrambf_v1(3, 25000, 2, 0)", granularity = 1 },
      { name = "idx_uuid_bloom", expression = "uuid", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_observed_minmax", expression = "observed_timestamp", type = "minmax", granularity = 1 },
      { name = "idx_timestamp_minmax", expression = "timestamp", type = "minmax", granularity = 1 },
    ]
    projections = [
      { name = "projection_aggregate_counts", query = "SELECT team_id, time_bucket, toStartOfMinute(timestamp), service_name, severity_text, resource_fingerprint, count() AS event_count GROUP BY team_id, time_bucket, toStartOfMinute(timestamp), service_name, severity_text, resource_fingerprint" },
    ]
  }
  routing = {
    read         = true
    read_columns = local.logs32_columns
  }
  deployment = merge({ read_cluster = "posthog_single_shard" }, local.deployment)
  names      = { storage = "logs32" }
}

module "logs34_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "logs_distributed"
  database = var.database
  layout   = "global"
  columns  = local.logs34_columns
  storage = {
    partition_by = "toDate(original_expiry_timestamp)"
    order_by     = "(team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp)"
    ttl          = var.ttl ? "original_expiry_timestamp" : null
    settings     = "add_minmax_index_for_numeric_columns = 1, allow_experimental_reverse_key = 1, index_granularity = 8192, index_granularity_bytes = 104857600, map_serialization_version = 'with_buckets', ttl_only_drop_parts = 1"
    indexes = [
      { name = "idx_severity_text_set", expression = "severity_text", type = "set(10)", granularity = 1 },
      { name = "idx_attributes_str_keys", expression = "mapKeys(attributes_map_str)", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attributes_str_values", expression = "mapValues(attributes_map_str)", type = "bloom_filter(0.001)", granularity = 1 },
      { name = "idx_mat_body_ipv4_matches", expression = "mat_body_ipv4_matches", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_body_ngram3", expression = "lower(body)", type = "ngrambf_v1(3, 25000, 2, 0)", granularity = 1 },
      { name = "idx_uuid_bloom", expression = "uuid", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_observed_minmax", expression = "observed_timestamp", type = "minmax", granularity = 1 },
      { name = "idx_timestamp_minmax", expression = "timestamp", type = "minmax", granularity = 1 },
    ]
    projections = [
      { name = "projection_aggregate_counts", query = "SELECT team_id, time_bucket, toStartOfMinute(timestamp), service_name, severity_text, resource_fingerprint, count() AS event_count GROUP BY team_id, time_bucket, toStartOfMinute(timestamp), service_name, severity_text, resource_fingerprint" },
    ]
  }
  routing = {
    read          = true
    read_columns  = local.test ? local.logs32_columns : local.logs34_columns
    write_columns = local.logs34_columns
  }
  kafka = {
    topic          = "clickhouse_logs"
    consumer_group = "clickhouse-logs-avro-new"
    format         = "Avro"
    arguments      = "settings"
    columns = [
      { name = "uuid", type = "String" },
      { name = "trace_id", type = "String" },
      { name = "span_id", type = "String" },
      { name = "trace_flags", type = "Int32" },
      { name = "timestamp", type = "DateTime64(6)" },
      { name = "observed_timestamp", type = "DateTime64(6)" },
      { name = "body", type = "String" },
      { name = "severity_text", type = "String" },
      { name = "severity_number", type = "Int32" },
      { name = "service_name", type = "String" },
      { name = "resource_attributes", type = "Map(LowCardinality(String), String)" },
      { name = "instrumentation_scope", type = "String" },
      { name = "event_name", type = "String" },
      { name = "attributes", type = "Map(LowCardinality(String), String)" },
      { name = "retention_days", type = "Nullable(Int32)" },
      { name = "pattern", type = "Nullable(String)" },
      { name = "pattern_version", type = "Nullable(Int32)" },
    ]
    settings = { input_format_avro_allow_missing_fields = "1", kafka_num_consumers = "1", kafka_poll_max_batch_size = "1000", kafka_poll_timeout_ms = "3000", kafka_skip_broken_messages = "100", kafka_thread_per_consumer = "1" }
  }
  mv_select = <<-SQL
uuid,
    trace_id,
    span_id,
    trace_flags,
    timestamp,
    observed_timestamp,
    body,
    severity_text,
    severity_number,
    service_name,
    instrumentation_scope,
    event_name,
    mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
    mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
    toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
    timestamp + toIntervalDay(if((retention_days IS NOT NULL) AND (retention_days > 0), retention_days, toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(15)))) AS original_expiry_timestamp,
    _partition,
    _topic,
    _offset,
    toInt64OrDefault(_headers.value[indexOf(_headers.name, 'record_count')], toInt64(1)) AS _record_count,
    toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_uncompressed')]) / _record_count AS _bytes_uncompressed,
    toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_compressed')]) / _record_count AS _bytes_compressed,
    ifNull(pattern, '') AS pattern,
    toUInt8(ifNull(pattern_version, 0)) AS pattern_version
  SQL
  deployment = merge({
    read_cluster     = "posthog_single_shard"
    kafka_collection = "warpstream_logs"
    }, local.deployment, {
    overrides = {
      "logs34"               = try(local.deployment.overrides["logs34"], {})
      "logs_distributed"     = try(local.deployment.overrides["logs_distributed"], {})
      "writable_logs34"      = merge({ settings = "background_insert_batch = 1" }, try(local.deployment.overrides["writable_logs34"], {}))
      "kafka_logs34_avro_mv" = try(local.deployment.overrides["kafka_logs34_avro_mv"], {})
      "kafka_logs_avro"      = try(local.deployment.overrides["kafka_logs_avro"], {})
    }
  })
  names = { storage = "logs34", write = "writable_logs34", mv = "kafka_logs34_avro_mv", kafka = "kafka_logs_avro" }
}

module "logs_billing_metrics_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "logs_billing_metrics_distributed"
  database = var.database
  layout   = "global"
  columns  = local.logs_billing_metrics_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toYYYYMM(time_bucket)"
    order_by     = "(team_id, time_bucket, service_name)"
    settings     = "deduplicate_merge_projection_mode = 'rebuild', index_granularity = 8192"
  }
  routing = {
    read = true
  }
  deployment = merge({
    read_cluster = "posthog_single_shard"
  }, local.deployment)
  names = { storage = "logs_billing_metrics" }
}

module "logs_kafka_metrics_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "logs_kafka_metrics_distributed"
  database = var.database
  layout   = "global"
  columns  = local.logs_kafka_metrics_columns
  storage = {
    engine   = "AggregatingMergeTree"
    order_by = "(_topic, _partition)"
  }
  routing = {
    read = true
  }
  deployment = merge({ read_cluster = "posthog_single_shard" }, local.deployment)
  names      = { storage = "logs_kafka_metrics" }
}

module "logs_pattern_buckets_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "logs_pattern_buckets_distributed"
  database = var.database
  layout   = "global"
  columns  = local.logs_pattern_buckets_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toDate(time_bucket)"
    primary_key  = "(team_id, time_bucket, service_name, namespace, environment, severity_text, pattern_version)"
    order_by     = "(team_id, time_bucket, service_name, namespace, environment, severity_text, pattern_version, pattern)"
    ttl          = var.ttl ? "time_bucket + toIntervalDay(42)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    read         = true
    read_columns = local.logs_pattern_buckets_columns
  }
  deployment = merge({ read_cluster = "posthog_single_shard" }, local.deployment)
  names      = { storage = "logs_pattern_buckets" }
}

module "logs_volume_buckets_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "logs_volume_buckets_distributed"
  database = var.database
  layout   = "global"
  columns  = local.logs_volume_buckets_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toDate(time_bucket)"
    order_by     = "(team_id, time_bucket, service_name, namespace, environment, severity_text)"
    ttl          = var.ttl ? "time_bucket + toIntervalDay(greatest(42, retention_days))" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 0"
  }
  routing = {
    read         = true
    read_columns = local.logs_volume_buckets_columns
  }
  deployment = merge({ read_cluster = "posthog_single_shard" }, local.deployment)
  names      = { storage = "logs_volume_buckets" }
}

# Tables that hold data, and the materialized views between them.

module "kafka_logs_avro_billing_metrics_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "kafka_logs_avro_billing_metrics_mv")
  database = var.database
  name     = "kafka_logs_avro_billing_metrics_mv"
  to_table = "${var.database}.logs_billing_metrics"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        service_name,
        sumSimpleState(_bytes_uncompressed) AS bytes_uncompressed,
        sumSimpleState(_bytes_compressed) AS bytes_compressed,
        sumSimpleState(1) AS record_count
    FROM
    (
        SELECT
            team_id,
            toStartOfInterval(timestamp, toIntervalMinute(1)) AS time_bucket,
            service_name AS service_name,
            _bytes_uncompressed,
            _bytes_compressed
        FROM ${var.database}.logs34
    )
    GROUP BY
        team_id,
        time_bucket,
        service_name
  SQL
  override = try(local.deployment.overrides["kafka_logs_avro_billing_metrics_mv"], {})

  depends_on = [
    module.logs34_family,
    module.logs_billing_metrics_family,
  ]
}

module "kafka_logs_avro_kafka_metrics_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "kafka_logs_avro_kafka_metrics_mv")
  database = var.database
  name     = "kafka_logs_avro_kafka_metrics_mv"
  to_table = "${var.database}.logs_kafka_metrics"
  query    = <<-SQL
    SELECT
        _partition,
        _topic,
        maxSimpleState(_offset) AS max_offset,
        maxSimpleState(observed_timestamp) AS max_observed_timestamp,
        maxSimpleState(timestamp) AS max_timestamp,
        maxSimpleState(now()) AS max_created_at,
        maxSimpleState(now() - observed_timestamp) AS max_lag
    FROM ${var.database}.logs34
    GROUP BY
        _partition,
        _topic
  SQL
  override = try(local.deployment.overrides["kafka_logs_avro_kafka_metrics_mv"], {})

  depends_on = [
    module.logs34_family,
    module.logs_kafka_metrics_family,
  ]
}





module "logs32_to_log_attributes" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "logs32_to_log_attributes")
  database = var.database
  name     = "logs32_to_log_attributes"
  to_table = "${var.database}.log_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
            arrayJoin(attributes) AS attribute,
            'log' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.logs32
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            resource_fingerprint,
            attributes
    )
  SQL
  override = try(local.deployment.overrides["logs32_to_log_attributes"], {})

  depends_on = [
    module.log_attributes_family,
    module.logs32_family,
  ]
}

module "logs32_to_resource_attributes" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "logs32_to_resource_attributes")
  database = var.database
  name     = "logs32_to_resource_attributes"
  to_table = "${var.database}.log_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            arrayJoin(resource_attributes) AS attribute,
            'resource' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.logs32
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            resource_fingerprint,
            resource_attributes
    )
  SQL
  override = try(local.deployment.overrides["logs32_to_resource_attributes"], {})

  depends_on = [
    module.log_attributes_family,
    module.logs32_family,
  ]
}


module "logs34_to_log_attributes3" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "logs34_to_log_attributes3")
  database = var.database
  name     = "logs34_to_log_attributes3"
  to_table = "${var.database}.log_attributes3"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        attribute_type,
        severity_text,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            severity_text AS severity_text,
            mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
            arrayJoin(attributes) AS attribute,
            'log' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.logs34
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            resource_fingerprint,
            severity_text,
            attributes
    )
  SQL
  override = try(local.deployment.overrides["logs34_to_log_attributes3"], {})

  depends_on = [
    module.log_attributes3_family,
    module.logs34_family,
  ]
}

module "logs34_to_resource_attributes3" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "logs34_to_resource_attributes3")
  database = var.database
  name     = "logs34_to_resource_attributes3"
  to_table = "${var.database}.log_attributes3"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        attribute_type,
        severity_text,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            severity_text AS severity_text,
            arrayJoin(resource_attributes) AS attribute,
            'resource' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.logs34
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            resource_fingerprint,
            severity_text,
            resource_attributes
    )
  SQL
  override = try(local.deployment.overrides["logs34_to_resource_attributes3"], {})

  depends_on = [
    module.log_attributes3_family,
    module.logs34_family,
  ]
}

module "logs34_to_volume_buckets" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "logs34_to_volume_buckets")
  database = var.database
  name     = "logs34_to_volume_buckets"
  to_table = "${var.database}.logs_volume_buckets"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        service_name,
        namespace,
        environment,
        severity_text,
        maxSimpleState(retention_days) AS retention_days,
        sumSimpleState(1) AS log_count
    FROM
    (
        SELECT
            team_id,
            toStartOfInterval(timestamp, toIntervalSecond(300), 'UTC') AS time_bucket,
            service_name,
            if((resource_attributes['k8s.namespace.name']) != '', resource_attributes['k8s.namespace.name'], resource_attributes['service.namespace']) AS namespace,
            if((resource_attributes['deployment.environment.name']) != '', resource_attributes['deployment.environment.name'], if((resource_attributes['deployment.environment']) != '', resource_attributes['deployment.environment'], resource_attributes['env'])) AS environment,
            lower(severity_text) AS severity_text,
            toUInt16(least(intDiv(greatest(dateDiff('microsecond', time_bucket, original_expiry_timestamp), 0) + 86399999999, 86400000000), 3650)) AS retention_days
        FROM ${var.database}.logs34
    )
    GROUP BY
        team_id,
        time_bucket,
        service_name,
        namespace,
        environment,
        severity_text
  SQL
  override = try(local.deployment.overrides["logs34_to_volume_buckets"], {})

  depends_on = [
    module.logs34_family,
    module.logs_volume_buckets_family,
  ]
}

# Objects only the test suite uses, such as materialized views that stand in for the kafka pipeline.

module "logs32_to_log_attributes3" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "logs32_to_log_attributes3")
  database = var.database
  name     = "logs32_to_log_attributes3"
  to_table = "${var.database}.log_attributes3"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        attribute_type,
        severity_text,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            severity_text AS severity_text,
            mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
            arrayJoin(attributes) AS attribute,
            'log' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.logs32
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            resource_fingerprint,
            severity_text,
            attributes
    )
  SQL
  override = try(local.deployment.overrides["logs32_to_log_attributes3"], {})

  depends_on = [
    module.log_attributes3_family,
    module.logs32_family,
  ]
}

module "logs32_to_resource_attributes3" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "logs32_to_resource_attributes3")
  database = var.database
  name     = "logs32_to_resource_attributes3"
  to_table = "${var.database}.log_attributes3"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        attribute_type,
        severity_text,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            severity_text AS severity_text,
            arrayJoin(resource_attributes) AS attribute,
            'resource' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.logs32
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            resource_fingerprint,
            severity_text,
            resource_attributes
    )
  SQL
  override = try(local.deployment.overrides["logs32_to_resource_attributes3"], {})

  depends_on = [
    module.log_attributes3_family,
    module.logs32_family,
  ]
}

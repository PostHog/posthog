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

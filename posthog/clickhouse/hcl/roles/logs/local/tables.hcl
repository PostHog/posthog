database "posthog" {
  table "log_attributes" {
    order_by     = ["team_id", "attribute_type", "time_bucket", "resource_fingerprint", "attribute_key", "attribute_value"]
    partition_by = "toDate(original_expiry_time_bucket)"
    settings = {
      deduplicate_merge_projection_mode = "drop"
      index_granularity                 = "8192"
      storage_policy                    = "default"
    }
    column "team_id" {
      type  = "Int32"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "time_bucket" {
      type  = "DateTime64(0)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "original_expiry_time_bucket" {
      type  = "DateTime64(0)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "service_name" {
      type  = "LowCardinality(String)"
      codec = "ZSTD(1)"
    }
    column "resource_fingerprint" {
      type    = "UInt64"
      default = "0"
      codec   = "DoubleDelta, ZSTD(1)"
    }
    column "attribute_key" {
      type  = "LowCardinality(String)"
      codec = "ZSTD(1)"
    }
    column "attribute_value" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "attribute_type" {
      type = "LowCardinality(String)"
    }
    index "idx_attribute_key" {
      expr        = "attribute_key"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attribute_value" {
      expr        = "attribute_value"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attribute_key_n3" {
      expr        = "attribute_key"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 1
    }
    index "idx_attribute_value_n3" {
      expr        = "attribute_value"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 1
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.log_attributes"
      replica_name = "{replica}-{shard}"
    }
  }
  table "logs" {
    column "time_bucket" {
      type         = "DateTime"
      materialized = "toStartOfDay(timestamp)"
      codec        = "DoubleDelta, ZSTD(1)"
    }
    column "original_expiry_timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "uuid" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "team_id" {
      type  = "Int32"
      codec = "ZSTD(1)"
    }
    column "trace_id" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "span_id" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "trace_flags" {
      type  = "Int32"
      codec = "ZSTD(1)"
    }
    column "timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "observed_timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "created_at" {
      type         = "DateTime64(6)"
      materialized = "now()"
      codec        = "DoubleDelta, ZSTD(1)"
    }
    column "body" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "severity_text" {
      type  = "LowCardinality(String)"
      codec = "ZSTD(1)"
    }
    column "severity_number" {
      type  = "Int32"
      codec = "ZSTD(1)"
    }
    column "service_name" {
      type  = "LowCardinality(String)"
      codec = "ZSTD(1)"
    }
    column "resource_attributes" {
      type  = "Map(LowCardinality(String), String)"
      codec = "ZSTD(1)"
    }
    column "resource_fingerprint" {
      type         = "UInt64"
      materialized = "cityHash64(resource_attributes)"
      codec        = "DoubleDelta, ZSTD(1)"
    }
    column "instrumentation_scope" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "event_name" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "attributes_map_str" {
      type  = "Map(LowCardinality(String), String)"
      codec = "ZSTD(1)"
    }
    column "level" {
      type  = "String"
      alias = "severity_text"
    }
    column "mat_body_ipv4_matches" {
      type  = "Array(String)"
      alias = "extractAll(body, '(\\\\d\\\\.((25[0-5]|(2[0-4]|1(0, 1)[0-9])(0, 1)[0-9])\\\\.)(2, 2)([0-9]))')"
    }
    column "time_minute" {
      type  = "DateTime"
      alias = "toStartOfMinute(timestamp)"
    }
    column "attributes" {
      type  = "Map(LowCardinality(String), String)"
      alias = "mapApply((k, v) -> (left(k, -5), v), attributes_map_str)"
    }
    column "attributes_map_float" {
      type         = "Map(LowCardinality(String), Float64)"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str))"
      codec        = "ZSTD(1)"
    }
    column "attributes_map_datetime" {
      type         = "Map(LowCardinality(String), DateTime64(6))"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str))"
      codec        = "ZSTD(1)"
    }
    column "_partition" {
      type  = "UInt32"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_topic" {
      type = "String"
    }
    column "_offset" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_bytes_uncompressed" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_bytes_compressed" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_record_count" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "logs32"
    }
  }
  table "logs32" {
    order_by     = ["team_id", "time_bucket", "service_name", "resource_fingerprint", "severity_text", "timestamp"]
    partition_by = "toDate(original_expiry_timestamp)"
    settings = {
      add_minmax_index_for_numeric_columns  = "1"
      allow_experimental_reverse_key        = "1"
      allow_remote_fs_zero_copy_replication = "1"
      index_granularity                     = "8192"
      index_granularity_bytes               = "104857600"
      storage_policy                        = "default"
      ttl_only_drop_parts                   = "1"
    }
    column "time_bucket" {
      type         = "DateTime"
      materialized = "toStartOfDay(timestamp)"
      codec        = "DoubleDelta, ZSTD(1)"
    }
    column "original_expiry_timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "uuid" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "team_id" {
      type  = "Int32"
      codec = "ZSTD(1)"
    }
    column "trace_id" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "span_id" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "trace_flags" {
      type  = "Int32"
      codec = "ZSTD(1)"
    }
    column "timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "observed_timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "created_at" {
      type         = "DateTime64(6)"
      materialized = "now()"
      codec        = "DoubleDelta, ZSTD(1)"
    }
    column "body" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "severity_text" {
      type  = "LowCardinality(String)"
      codec = "ZSTD(1)"
    }
    column "severity_number" {
      type  = "Int32"
      codec = "ZSTD(1)"
    }
    column "service_name" {
      type  = "LowCardinality(String)"
      codec = "ZSTD(1)"
    }
    column "resource_attributes" {
      type  = "Map(LowCardinality(String), String)"
      codec = "ZSTD(1)"
    }
    column "resource_fingerprint" {
      type         = "UInt64"
      materialized = "cityHash64(resource_attributes)"
      codec        = "DoubleDelta, ZSTD(1)"
    }
    column "instrumentation_scope" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "event_name" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "attributes_map_str" {
      type  = "Map(LowCardinality(String), String)"
      codec = "ZSTD(1)"
    }
    column "level" {
      type  = "String"
      alias = "severity_text"
    }
    column "mat_body_ipv4_matches" {
      type  = "Array(String)"
      alias = "extractAll(body, '(\\\\d\\\\.((25[0-5]|(2[0-4]|1(0, 1)[0-9])(0, 1)[0-9])\\\\.)(2, 2)([0-9]))')"
    }
    column "time_minute" {
      type  = "DateTime"
      alias = "toStartOfMinute(timestamp)"
    }
    column "attributes" {
      type  = "Map(LowCardinality(String), String)"
      alias = "mapApply((k, v) -> (left(k, -5), v), attributes_map_str)"
    }
    column "attributes_map_float" {
      type         = "Map(LowCardinality(String), Float64)"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str))"
      codec        = "ZSTD(1)"
    }
    column "attributes_map_datetime" {
      type         = "Map(LowCardinality(String), DateTime64(6))"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str))"
      codec        = "ZSTD(1)"
    }
    column "_partition" {
      type  = "UInt32"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_topic" {
      type = "String"
    }
    column "_offset" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_bytes_uncompressed" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_bytes_compressed" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_record_count" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    index "idx_severity_text_set" {
      expr        = "severity_text"
      type        = "set(10)"
      granularity = 1
    }
    index "idx_attributes_str_keys" {
      expr        = "mapKeys(attributes_map_str)"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attributes_str_values" {
      expr        = "mapValues(attributes_map_str)"
      type        = "bloom_filter(0.001)"
      granularity = 1
    }
    index "idx_mat_body_ipv4_matches" {
      expr        = "mat_body_ipv4_matches"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_body_ngram3" {
      expr        = "lower(body)"
      type        = "ngrambf_v1(3, 25000, 2, 0)"
      granularity = 1
    }
    index "idx_uuid_bloom" {
      expr        = "uuid"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_observed_minmax" {
      expr        = "observed_timestamp"
      type        = "minmax"
      granularity = 1
    }
    index "idx_timestamp_minmax" {
      expr        = "timestamp"
      type        = "minmax"
      granularity = 1
    }
    projection "projection_aggregate_counts" {
      query = <<SQL
SELECT
  team_id,
  time_bucket,
  toStartOfMinute(timestamp),
  service_name,
  severity_text,
  resource_fingerprint,
  count() AS event_count
GROUP BY
  team_id, time_bucket, toStartOfMinute(timestamp), service_name, severity_text, resource_fingerprint
SQL

    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.logs32"
      replica_name = "{replica}-{shard}"
    }
  }
  patch_table "logs34" {
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.logs34"
      replica_name = "{replica}-{shard}"
    }
  }
  patch_materialized_view "kafka_logs_avro_billing_metrics_mv" {
    query = <<SQL
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
    FROM posthog.logs34
  )
GROUP BY
  team_id, time_bucket, service_name
SQL

  }
  materialized_view "logs32_to_log_attributes" {
    to_table = "posthog.log_attributes"
    query    = <<SQL
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
    FROM posthog.logs32
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, attributes
  )
SQL

    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_fingerprint" {
      type = "UInt64"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type = "String"
    }
    column "attribute_type" {
      type = "LowCardinality(String)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
  }
  materialized_view "logs32_to_resource_attributes" {
    to_table = "posthog.log_attributes"
    query    = <<SQL
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
    FROM posthog.logs32
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, resource_attributes
  )
SQL

    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_fingerprint" {
      type = "UInt64"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type = "String"
    }
    column "attribute_type" {
      type = "LowCardinality(String)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
  }

  patch_table "trace_spans" {
    projection "projection_aggregate_counts" {
      query = <<SQL
SELECT
  team_id,
  time_bucket,
  toStartOfMinute(timestamp),
  service_name,
  resource_fingerprint,
  is_root_span,
  count() AS event_count
GROUP BY
  team_id, time_bucket, toStartOfMinute(timestamp), service_name, resource_fingerprint, is_root_span
SQL

    }
    projection "projection_index_trace_id" {
      query = <<SQL
SELECT _part_offset
ORDER BY trace_id
SQL

    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.trace_spans"
      replica_name = "{replica}-{shard}"
    }
  }
  patch_materialized_view "kafka_trace_spans_avro_mv" {
    query = <<SQL
SELECT
  * EXCEPT(attributes, resource_attributes, kind, flags, dropped_attributes_count, dropped_events_count, dropped_links_count, status_code),
  toInt8(kind) AS kind,
  toUInt32(flags) AS flags,
  toUInt32(dropped_attributes_count) AS dropped_attributes_count,
  toUInt32(dropped_events_count) AS dropped_events_count,
  toUInt32(dropped_links_count) AS dropped_links_count,
  toInt16(status_code) AS status_code,
  mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
  mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
  toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
  observed_timestamp
  + toIntervalDay(
    toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(15))
  ) AS original_expiry_timestamp,
  _partition,
  _topic,
  _offset,
  toInt64OrDefault(_headers.value[indexOf(_headers.name, 'record_count')], toInt64(1)) AS _record_count,
  toInt64OrDefault(_headers.value[indexOf(_headers.name, 'bytes_uncompressed')], toInt64(0)) AS _bytes_uncompressed,
  toInt64OrDefault(_headers.value[indexOf(_headers.name, 'bytes_compressed')], toInt64(0)) AS _bytes_compressed
FROM posthog.kafka_trace_spans_avro
SQL

  }
}

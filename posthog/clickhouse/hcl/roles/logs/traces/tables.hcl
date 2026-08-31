# The trace-spans suite, hosted by every logs node. Env deltas are patch_table /
# patch_materialized_view blocks in the env layers, never second definitions: the
# prods shard trace_attributes and trace_spans onto the logs cluster and carry a
# second span-count projection, dev keeps the single-shard ZK paths.
database "posthog" {
  table "trace_attributes" {
    order_by     = ["team_id", "attribute_type", "time_bucket", "resource_fingerprint", "attribute_key", "attribute_value"]
    partition_by = "toDate(original_expiry_time_bucket)"
    ttl          = "original_expiry_time_bucket"
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int32"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_fingerprint" {
      type    = "UInt64"
      default = "0"
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
    index "idx_attribute_key" {
      expr        = "attribute_key"
      type        = "bloom_filter(0.01)"
      granularity = 4
    }
    index "idx_attribute_value" {
      expr        = "attribute_value"
      type        = "bloom_filter(0.01)"
      granularity = 4
    }
    index "idx_attribute_key_n3" {
      expr        = "attribute_key"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 4
    }
    index "idx_attribute_value_n3" {
      expr        = "attribute_value"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 4
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.trace_attributes"
      replica_name = "{replica}-{shard}"
    }
  }

  table "trace_attributes2" {
    order_by     = ["team_id", "attribute_type", "time_bucket", "resource_fingerprint", "attribute_key", "attribute_value"]
    partition_by = "toDate(original_expiry_time_bucket)"
    ttl          = "original_expiry_time_bucket"
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int32"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_fingerprint" {
      type    = "UInt64"
      default = "0"
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
    index "idx_attribute_key" {
      expr        = "attribute_key"
      type        = "bloom_filter(0.01)"
      granularity = 4
    }
    index "idx_attribute_value" {
      expr        = "attribute_value"
      type        = "bloom_filter(0.01)"
      granularity = 4
    }
    index "idx_attribute_key_n3" {
      expr        = "attribute_key"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 4
    }
    index "idx_attribute_value_n3" {
      expr        = "attribute_value"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 4
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.trace_attributes2"
      replica_name = "{replica}-{shard}"
    }
  }

  table "trace_attributes_distributed" {
    column "team_id" {
      type = "Int32"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_fingerprint" {
      type    = "UInt64"
      default = "0"
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
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "trace_attributes"
    }
  }

  table "kafka_trace_spans_avro" {
    column "uuid" {
      type = "String"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "parent_span_id" {
      type = "String"
    }
    column "trace_state" {
      type = "String"
    }
    column "name" {
      type = "String"
    }
    column "kind" {
      type = "Int32"
    }
    column "flags" {
      type = "Int32"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "end_time" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "service_name" {
      type = "String"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "dropped_attributes_count" {
      type = "Int32"
    }
    column "events" {
      type = "Array(String)"
    }
    column "dropped_events_count" {
      type = "Int32"
    }
    column "links" {
      type = "Array(String)"
    }
    column "dropped_links_count" {
      type = "Int32"
    }
    column "status_code" {
      type = "Int32"
    }
    engine "kafka" {
      broker_list          = "warpstream_traces"
      topic_list           = "kafka_topic_list = 'clickhouse_traces'"
      group_name           = "kafka_group_name = 'clickhouse-traces-avro'"
      format               = "kafka_format = 'Avro'"
      num_consumers        = 8
      skip_broken_messages = 100
      poll_timeout_ms      = 3000
      poll_max_batch_size  = 1000
      thread_per_consumer  = true
    }
  }

  table "trace_spans" {
    order_by     = ["team_id", "time_bucket", "service_name", "resource_fingerprint", "status_code", "name", "timestamp"]
    partition_by = "toDate(original_expiry_timestamp)"
    ttl          = "original_expiry_timestamp"
    settings = {
      allow_part_offset_column_in_projections = "1"
      index_granularity                       = "8192"
      index_granularity_bytes                 = "104857600"
      map_serialization_version               = "with_buckets"
      ttl_only_drop_parts                     = "1"
    }
    column "time_bucket" {
      type         = "DateTime"
      materialized = "toStartOfInterval(timestamp, toIntervalHour(4))"
    }
    column "original_expiry_timestamp" {
      type = "DateTime64(6)"
    }
    column "uuid" {
      type = "String"
    }
    column "team_id" {
      type = "Int32"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "parent_span_id" {
      type = "String"
    }
    column "is_root_span" {
      type         = "Bool"
      materialized = "replaceAll(trimRight(parent_span_id, '='), 'A', '') = ''"
    }
    column "trace_state" {
      type = "String"
    }
    column "name" {
      type = "LowCardinality(String)"
    }
    column "kind" {
      type = "Int8"
    }
    column "flags" {
      type = "UInt32"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "end_time" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "created_at" {
      type         = "DateTime64(6)"
      materialized = "now()"
    }
    column "duration_nano" {
      type         = "UInt64"
      materialized = "toUInt64(dateDiff('microsecond', timestamp, end_time)) * 1000"
    }
    column "status_code" {
      type = "Int16"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "resource_fingerprint" {
      type         = "UInt64"
      materialized = "cityHash64(resource_attributes)"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "attributes_map_str" {
      type = "Map(LowCardinality(String), String)"
    }
    column "attributes" {
      type  = "Map(LowCardinality(String), String)"
      alias = "mapApply((k, v) -> (left(k, -5), v), attributes_map_str)"
    }
    column "attributes_map_float" {
      type         = "Map(LowCardinality(String), Float64)"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str))"
    }
    column "attributes_map_datetime" {
      type         = "Map(LowCardinality(String), DateTime64(6))"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str))"
    }
    column "dropped_attributes_count" {
      type = "UInt32"
    }
    column "dropped_events_count" {
      type = "UInt32"
    }
    column "dropped_links_count" {
      type = "UInt32"
    }
    column "events" {
      type = "Array(String)"
    }
    column "links" {
      type = "Array(String)"
    }
    column "_partition" {
      type = "UInt32"
    }
    column "_topic" {
      type = "String"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_bytes_uncompressed" {
      type = "UInt64"
    }
    column "_bytes_compressed" {
      type = "UInt64"
    }
    column "_record_count" {
      type = "UInt64"
    }
    index "idx_name" {
      expr        = "name"
      type        = "ngrambf_v1(4, 5000, 2, 0)"
      granularity = 16
    }
    index "idx_kind" {
      expr        = "kind"
      type        = "minmax"
      granularity = 4
    }
    index "idx_duration" {
      expr        = "duration_nano"
      type        = "minmax"
      granularity = 1
    }
    index "idx_status_code" {
      expr        = "status_code"
      type        = "minmax"
      granularity = 1
    }
    index "idx_timestamp_minmax" {
      expr        = "timestamp"
      type        = "minmax"
      granularity = 1
    }
    index "idx_observed_minmax" {
      expr        = "observed_timestamp"
      type        = "minmax"
      granularity = 1
    }
    index "idx_attributes_str_keys" {
      expr        = "mapKeys(attributes_map_str)"
      type        = "bloom_filter(0.01)"
      granularity = 16
    }
    index "idx_attributes_str_values" {
      expr        = "mapValues(attributes_map_str)"
      type        = "bloom_filter(0.001)"
      granularity = 16
    }
    index "idx_trace_bloom_part" {
      expr        = "trace_id"
      type        = "bloom_filter(0.00001)"
      granularity = 99999
    }
    index "idx_span_id_bloom_part" {
      expr        = "span_id"
      type        = "bloom_filter(0.00001)"
      granularity = 99999
    }
    projection "projection_index_span_id" {
      query = <<SQL
SELECT _part_offset
ORDER BY span_id
SQL

    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/posthog.trace_spans"
      replica_name = "{replica}"
    }
  }

  table "trace_spans_distributed" {
    column "time_bucket" {
      type         = "DateTime"
      materialized = "toStartOfInterval(timestamp, toIntervalHour(4))"
    }
    column "original_expiry_timestamp" {
      type = "DateTime64(6)"
    }
    column "uuid" {
      type = "String"
    }
    column "team_id" {
      type = "Int32"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "parent_span_id" {
      type = "String"
    }
    column "is_root_span" {
      type         = "Bool"
      materialized = "replaceAll(trimRight(parent_span_id, '='), 'A', '') = ''"
    }
    column "trace_state" {
      type = "String"
    }
    column "name" {
      type = "LowCardinality(String)"
    }
    column "kind" {
      type = "Int8"
    }
    column "flags" {
      type = "UInt32"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "end_time" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "created_at" {
      type         = "DateTime64(6)"
      materialized = "now()"
    }
    column "duration_nano" {
      type         = "UInt64"
      materialized = "toUInt64(dateDiff('microsecond', timestamp, end_time)) * 1000"
    }
    column "status_code" {
      type = "Int16"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "resource_fingerprint" {
      type         = "UInt64"
      materialized = "cityHash64(resource_attributes)"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "attributes_map_str" {
      type = "Map(LowCardinality(String), String)"
    }
    column "attributes" {
      type  = "Map(LowCardinality(String), String)"
      alias = "mapApply((k, v) -> (left(k, -5), v), attributes_map_str)"
    }
    column "attributes_map_float" {
      type         = "Map(LowCardinality(String), Float64)"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str))"
    }
    column "attributes_map_datetime" {
      type         = "Map(LowCardinality(String), DateTime64(6))"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str))"
    }
    column "dropped_attributes_count" {
      type = "UInt32"
    }
    column "dropped_events_count" {
      type = "UInt32"
    }
    column "dropped_links_count" {
      type = "UInt32"
    }
    column "events" {
      type = "Array(String)"
    }
    column "links" {
      type = "Array(String)"
    }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "trace_spans"
    }
  }

  materialized_view "trace_span_to_attributes" {
    to_table = "posthog.trace_attributes"
    query = file("sql/trace_span_to_attributes.sql")
    column "team_id" {
      type = "Int32"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "time_bucket" {
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

  materialized_view "trace_span_to_attributes2" {
    to_table = "posthog.trace_attributes2"
    query = file("sql/trace_span_to_attributes.sql")
    column "team_id" {
      type = "Int32"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "time_bucket" {
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

  materialized_view "trace_span_to_resource_attributes" {
    to_table = "posthog.trace_attributes"
    query = file("sql/trace_span_to_resource_attributes.sql")
    column "team_id" {
      type = "Int32"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "time_bucket" {
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

  materialized_view "trace_span_to_resource_attributes2" {
    to_table = "posthog.trace_attributes2"
    query = file("sql/trace_span_to_resource_attributes.sql")
    column "team_id" {
      type = "Int32"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "time_bucket" {
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

  materialized_view "trace_span_to_span_attributes" {
    to_table = "posthog.trace_attributes"
    query = file("sql/trace_span_to_span_attributes.sql")
    column "team_id" {
      type = "Int32"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "time_bucket" {
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

  materialized_view "trace_span_to_span_attributes2" {
    to_table = "posthog.trace_attributes2"
    query = file("sql/trace_span_to_span_attributes.sql")
    column "team_id" {
      type = "Int32"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "time_bucket" {
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

  materialized_view "kafka_trace_spans_avro_mv" {
    to_table = "posthog.trace_spans"
    query = file("sql/kafka_trace_spans_avro_mv.sql")
    column "uuid" {
      type = "String"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "parent_span_id" {
      type = "String"
    }
    column "trace_state" {
      type = "String"
    }
    column "name" {
      type = "String"
    }
    column "kind" {
      type = "Int8"
    }
    column "flags" {
      type = "UInt32"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "end_time" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "service_name" {
      type = "String"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "attributes_map_str" {
      type = "Map(LowCardinality(String), String)"
    }
    column "dropped_attributes_count" {
      type = "UInt32"
    }
    column "events" {
      type = "Array(String)"
    }
    column "dropped_events_count" {
      type = "UInt32"
    }
    column "links" {
      type = "Array(String)"
    }
    column "dropped_links_count" {
      type = "UInt32"
    }
    column "status_code" {
      type = "Int16"
    }
    column "team_id" {
      type = "Int32"
    }
    column "original_expiry_timestamp" {
      type = "DateTime64(6)"
    }
  }
}

# LOGS role — managed logs/traces/metrics objects extracted from *-logs.hcl dumps.
database "posthog" {
  view "custom_metrics" {
    query = "SELECT * REPLACE(toFloat64(value) AS value) FROM posthog.custom_metrics_test UNION ALL SELECT * REPLACE(toFloat64(value) AS value) FROM posthog.custom_metrics_replication_queue UNION ALL SELECT * REPLACE(toFloat64(value) AS value) FROM posthog.custom_metrics_server_crash UNION ALL SELECT * FROM posthog.custom_metrics_table_sizes UNION ALL SELECT * REPLACE(toFloat64(value) AS value) FROM posthog.custom_metrics_part_counts UNION ALL SELECT * REPLACE(toFloat64(value) AS value) FROM posthog.custom_metrics_dictionaries UNION ALL SELECT 'ClickHouseCustomMetric_S3DiskBytesUsed' AS name, map('instance', hostname(), 'disk', disk_name) AS labels, toFloat64(sum(bytes_on_disk)) AS value, 'Bytes currently used by ClickHouse parts on S3-backed disks on this node' AS help, 'gauge' AS type FROM system.parts WHERE disk_name IN ('s3disk', 'cache') GROUP BY disk_name UNION ALL SELECT 'ClickHouseCustomMetric_MergeFailures15m' AS name, map('instance', hostname()) AS labels, toFloat64(count()) AS value, 'Number of failed merge operations in the last 15 minutes' AS help, 'gauge' AS type FROM system.part_log WHERE (event_time >= (now() - toIntervalMinute(15))) AND (event_type = 'MergeParts') AND (error > 0) AND (merge_reason != 'NotAMerge') AND (error != 40) UNION ALL SELECT 'ClickHouseCustomMetric_MergeRetriesMaxPerTable15m' AS name, map('instance', hostname()) AS labels, toFloat64(max(cnt)) AS value, 'Max failed merge retries for any single table in the last 15 minutes' AS help, 'gauge' AS type FROM (SELECT count() AS cnt FROM system.part_log WHERE (event_time >= (now() - toIntervalMinute(15))) AND (event_type = 'MergeParts') AND (error > 0) AND (merge_reason != 'NotAMerge') AND (error != 40) GROUP BY database, `table`, partition_id)"
  }
  materialized_view "kafka_logs_avro_kafka_metrics_mv" {
    to_table = "posthog.logs_kafka_metrics"
    query    = "SELECT _partition, _topic, maxSimpleState(_offset) AS max_offset, maxSimpleState(observed_timestamp) AS max_observed_timestamp, maxSimpleState(timestamp) AS max_timestamp, maxSimpleState(now()) AS max_created_at, maxSimpleState(now() - observed_timestamp) AS max_lag FROM posthog.logs34 GROUP BY _partition, _topic"
    column "_partition" {
      type = "UInt32"
    }
    column "_topic" {
      type = "String"
    }
    column "max_offset" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "max_observed_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6))"
    }
    column "max_created_at" {
      type = "SimpleAggregateFunction(max, DateTime)"
    }
    column "max_lag" {
      type = "SimpleAggregateFunction(max, Decimal(18, 6))"
    }
  }
  table "kafka_metrics_avro" {
    column "uuid" {
      type = "String"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "trace_flags" {
      type = "Nullable(Int32)"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "service_name" {
      type = "Nullable(String)"
    }
    column "metric_name" {
      type = "Nullable(String)"
    }
    column "metric_type" {
      type = "Nullable(String)"
    }
    column "value" {
      type = "Nullable(Float64)"
    }
    column "count" {
      type = "Nullable(Int64)"
    }
    column "histogram_bounds" {
      type = "Array(Float64)"
    }
    column "histogram_counts" {
      type = "Array(Int64)"
    }
    column "unit" {
      type = "Nullable(String)"
    }
    column "aggregation_temporality" {
      type = "Nullable(String)"
    }
    column "is_monotonic" {
      type = "Nullable(UInt8)"
    }
    column "resource_attributes" {
      type = "Map(String, String)"
    }
    column "instrumentation_scope" {
      type = "Nullable(String)"
    }
    column "attributes" {
      type = "Map(String, String)"
    }
    engine "kafka" {
      broker_list          = "warpstream_metrics"
      topic_list           = "kafka_topic_list = 'clickhouse_metrics'"
      group_name           = "kafka_group_name = 'clickhouse-metrics-avro-new'"
      format               = "kafka_format = 'Avro'"
      num_consumers        = 8
      skip_broken_messages = 100
      poll_timeout_ms      = 3000
      poll_max_batch_size  = 1000
      thread_per_consumer  = true
    }
  }
  materialized_view "kafka_metrics_avro_kafka_metrics_mv" {
    to_table = "posthog.metrics_kafka_metrics"
    query    = "SELECT _partition, _topic, maxSimpleState(_offset) AS max_offset, maxSimpleState(observed_timestamp) AS max_observed_timestamp, maxSimpleState(timestamp) AS max_timestamp, maxSimpleState(now()) AS max_created_at, maxSimpleState(now() - observed_timestamp) AS max_lag FROM posthog.kafka_metrics_avro GROUP BY _partition, _topic"
    column "_partition" {
      type = "UInt64"
    }
    column "_topic" {
      type = "LowCardinality(String)"
    }
    column "max_offset" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "max_observed_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6))"
    }
    column "max_created_at" {
      type = "SimpleAggregateFunction(max, DateTime)"
    }
    column "max_lag" {
      type = "SimpleAggregateFunction(max, Decimal(18, 6))"
    }
  }
  materialized_view "kafka_metrics_avro_mv" {
    to_table = "posthog.metrics1"
    query    = "SELECT uuid, trace_id, span_id, ifNull(trace_flags, 0) AS trace_flags, timestamp, observed_timestamp, ifNull(service_name, '') AS service_name, ifNull(metric_name, '') AS metric_name, ifNull(metric_type, '') AS metric_type, ifNull(value, 0) AS value, toUInt64(ifNull(count, 1)) AS count, histogram_bounds, arrayMap(x -> toUInt64(x), histogram_counts) AS histogram_counts, ifNull(unit, '') AS unit, ifNull(aggregation_temporality, '') AS aggregation_temporality, ifNull(is_monotonic, 0) AS is_monotonic, mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes, ifNull(instrumentation_scope, '') AS instrumentation_scope, mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str, mapSort(mapFilter((k, v) -> isNotNull(v), mapApply((k, v) -> (concat(k, '__float'), toFloat64OrNull(JSONExtract(v, 'String'))), attributes))) AS attributes_map_float, toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id FROM posthog.kafka_metrics_avro SETTINGS min_insert_block_size_rows=0, min_insert_block_size_bytes=0"
    column "uuid" {
      type = "String"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "trace_flags" {
      type = "Int32"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "service_name" {
      type = "String"
    }
    column "metric_name" {
      type = "String"
    }
    column "metric_type" {
      type = "String"
    }
    column "value" {
      type = "Float64"
    }
    column "count" {
      type = "UInt64"
    }
    column "histogram_bounds" {
      type = "Array(Float64)"
    }
    column "histogram_counts" {
      type = "Array(UInt64)"
    }
    column "unit" {
      type = "String"
    }
    column "aggregation_temporality" {
      type = "String"
    }
    column "is_monotonic" {
      type = "UInt8"
    }
    column "resource_attributes" {
      type = "Map(String, String)"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "attributes_map_str" {
      type = "Map(String, String)"
    }
    column "attributes_map_float" {
      type = "Map(String, Nullable(Float64))"
    }
    column "team_id" {
      type = "Int32"
    }
  }
  table "log_attributes2" {
    order_by     = ["team_id", "attribute_type", "time_bucket", "resource_fingerprint", "attribute_key", "attribute_value"]
    partition_by = "toDate(time_bucket)"
    ttl          = "time_bucket + toIntervalDay(15)"
    settings = {
      deduplicate_merge_projection_mode = "drop"
      index_granularity                 = "8192"
    }
    column "team_id" {
      type = "Int32"
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
      type  = "String"
      codec = "ZSTD(5)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "attribute_type" {
      type    = "LowCardinality(String)"
      default = "'log'"
    }
    column "original_expiry_time_bucket" {
      type    = "DateTime"
      default = "now()"
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
      zoo_path     = "/clickhouse/tables/logs/{shard}/log_attributes34"
      replica_name = "{replica}"
    }
  }
  materialized_view "logs34_to_log_attributes" {
    to_table = "posthog.log_attributes2"
    query    = "SELECT team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, attribute_key, attribute_value, attribute_type, attribute_count FROM (SELECT team_id AS team_id, toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket, toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket, service_name AS service_name, resource_fingerprint, mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes, arrayJoin(attributes) AS attribute, 'log' AS attribute_type, attribute.1 AS attribute_key, attribute.2 AS attribute_value, sumSimpleState(1) AS attribute_count FROM posthog.logs34 GROUP BY team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, attributes)"
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
  materialized_view "logs34_to_resource_attributes" {
    to_table = "posthog.log_attributes2"
    query    = "SELECT team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, attribute_key, attribute_value, attribute_type, attribute_count FROM (SELECT team_id AS team_id, toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket, toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket, service_name AS service_name, resource_fingerprint, arrayJoin(resource_attributes) AS attribute, 'resource' AS attribute_type, attribute.1 AS attribute_key, attribute.2 AS attribute_value, sumSimpleState(1) AS attribute_count FROM posthog.logs34 GROUP BY team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, resource_attributes)"
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
  table "logs_billing_metrics" {
    order_by     = ["team_id", "time_bucket", "service_name"]
    partition_by = "toYYYYMM(time_bucket)"
    settings = {
      deduplicate_merge_projection_mode = "rebuild"
      index_granularity                 = "8192"
    }
    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "bytes_uncompressed" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "bytes_compressed" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "record_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/logs_billing_metrics"
      replica_name = "{replica}"
    }
  }
  table "logs_billing_metrics_distributed" {
    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "bytes_uncompressed" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "bytes_compressed" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "record_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "logs_billing_metrics"
    }
  }
  table "logs_kafka_metrics" {
    order_by = ["_topic", "_partition"]
    settings = {
      deduplicate_merge_projection_mode = "rebuild"
      index_granularity                 = "8192"
    }
    column "_partition" {
      type = "UInt32"
    }
    column "_topic" {
      type = "String"
    }
    column "max_offset" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "max_observed_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_created_at" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_lag" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/logs_kafka_metrics"
      replica_name = "{replica}"
    }
  }
  table "logs_kafka_metrics_distributed" {
    column "_partition" {
      type = "UInt32"
    }
    column "_topic" {
      type = "String"
    }
    column "max_offset" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "max_observed_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_created_at" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_lag" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "logs_kafka_metrics"
    }
  }
  table "metric_attributes" {
    order_by     = ["team_id", "attribute_type", "time_bucket", "resource_fingerprint", "attribute_key", "attribute_value"]
    partition_by = "toDate(time_bucket)"
    settings = {
      deduplicate_merge_projection_mode = "drop"
      index_granularity                 = "8192"
    }
    column "team_id" {
      type = "Int32"
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
      zoo_path     = "/clickhouse/tables/logs/{shard}/posthog.metric_attributes"
      replica_name = "{replica}"
    }
  }
  materialized_view "metrics1_to_metric_attributes" {
    to_table = "posthog.metric_attributes"
    query    = "SELECT team_id, time_bucket, service_name, resource_fingerprint, attribute_key, attribute_value, attribute_type, attribute_count FROM (SELECT team_id AS team_id, toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket, service_name AS service_name, resource_fingerprint, mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes, arrayJoin(attributes) AS attribute, 'metric' AS attribute_type, attribute.1 AS attribute_key, attribute.2 AS attribute_value, sumSimpleState(1) AS attribute_count FROM posthog.metrics1 GROUP BY team_id, time_bucket, service_name, resource_fingerprint, attributes)"
    column "team_id" {
      type = "Int32"
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
  materialized_view "metrics1_to_resource_attributes" {
    to_table = "posthog.metric_attributes"
    query    = "SELECT team_id, time_bucket, service_name, resource_fingerprint, attribute_key, attribute_value, attribute_type, attribute_count FROM (SELECT team_id AS team_id, toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket, service_name AS service_name, resource_fingerprint, arrayJoin(resource_attributes) AS attribute, 'resource' AS attribute_type, attribute.1 AS attribute_key, attribute.2 AS attribute_value, sumSimpleState(1) AS attribute_count FROM posthog.metrics1 GROUP BY team_id, time_bucket, service_name, resource_fingerprint, resource_attributes)"
    column "team_id" {
      type = "Int32"
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
  table "metrics_kafka_metrics" {
    order_by = ["_topic", "_partition"]
    settings = {
      index_granularity = "8192"
    }
    column "_partition" {
      type = "UInt32"
    }
    column "_topic" {
      type = "String"
    }
    column "max_offset" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "max_observed_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_created_at" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_lag" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/posthog.metrics_kafka_metrics"
      replica_name = "{replica}"
    }
  }
}

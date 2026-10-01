module "trace_attributes_family" {
  source = "../../lib/table_family"

  name     = "trace_attributes_distributed"
  database = var.database
  layout   = "global"
  columns  = local.trace_attributes_columns
  storage = {
    partition_by = "toDate(original_expiry_time_bucket)"
    order_by     = "(team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)"
    ttl          = var.ttl ? "original_expiry_time_bucket" : null
    indexes = [
      { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 4 },
      { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 4 },
      { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 4 },
      { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 4 },
    ]
  }
  routing = {
    read = true
  }
  sharding_key = ""
  deployment = merge({
    cluster      = "posthog"
    read_cluster = "posthog_single_shard"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["trace_attributes", "trace_attributes_distributed"], name) }
  })
  names = { storage = "trace_attributes" }
}

module "trace_attributes2_family" {
  source = "../../lib/table_family"

  name     = "trace_attributes2"
  database = var.database
  layout   = "global"
  columns  = local.trace_attributes_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toDate(original_expiry_time_bucket)"
    order_by     = "(team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)"
    ttl          = var.ttl ? "original_expiry_time_bucket" : null
    indexes = [
      { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 4 },
      { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 4 },
      { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 4 },
      { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 4 },
    ]
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["trace_attributes2"], name) }
  })
}

module "trace_spans_family" {
  source = "../../lib/table_family"

  name     = "trace_spans_distributed"
  database = var.database
  layout   = "global"
  columns  = local.trace_spans_columns
  storage = {
    partition_by = "toDate(original_expiry_timestamp)"
    order_by     = "(team_id, time_bucket, service_name, resource_fingerprint, status_code, name, timestamp)"
    ttl          = var.ttl ? "original_expiry_timestamp" : null
    settings     = "allow_part_offset_column_in_projections = 1, index_granularity = 8192, index_granularity_bytes = 104857600, map_serialization_version = 'with_buckets', ttl_only_drop_parts = 1"
    indexes = [
      { name = "idx_name", expression = "name", type = "ngrambf_v1(4, 5000, 2, 0)", granularity = 16 },
      { name = "idx_kind", expression = "kind", type = "minmax", granularity = 4 },
      { name = "idx_duration", expression = "duration_nano", type = "minmax", granularity = 1 },
      { name = "idx_status_code", expression = "status_code", type = "minmax", granularity = 1 },
      { name = "idx_timestamp_minmax", expression = "timestamp", type = "minmax", granularity = 1 },
      { name = "idx_observed_minmax", expression = "observed_timestamp", type = "minmax", granularity = 1 },
      { name = "idx_attributes_str_keys", expression = "mapKeys(attributes_map_str)", type = "bloom_filter(0.01)", granularity = 16 },
      { name = "idx_attributes_str_values", expression = "mapValues(attributes_map_str)", type = "bloom_filter(0.001)", granularity = 16 },
      { name = "idx_trace_bloom_part_v2", expression = "trace_id", type = "bloom_filter(0.05)", granularity = 99999 },
      { name = "idx_span_id_bloom_part_v2", expression = "span_id", type = "bloom_filter(0.05)", granularity = 99999 },
    ]
    projections = [
      { name = "projection_index_team_span_id", query = "SELECT team_id, _part_offset ORDER BY span_id" },
      { name = "projection_index_team_trace_id", query = "SELECT team_id, _part_offset ORDER BY trace_id" },
      { name = "projection_aggregate_counts", query = "SELECT team_id, time_bucket, toStartOfMinute(timestamp), service_name, resource_fingerprint, is_root_span, count() AS event_count GROUP BY team_id, time_bucket, toStartOfMinute(timestamp), service_name, resource_fingerprint, is_root_span" },
    ]
  }
  routing = {
    read         = true
    write        = false
    read_columns = local.trace_spans_columns
  }
  sharding_key = ""
  kafka = {
    topic          = "clickhouse_traces"
    consumer_group = "clickhouse-traces-avro"
    format         = "Avro"
    arguments      = "settings"
    columns = [
      { name = "uuid", type = "String" },
      { name = "trace_id", type = "String" },
      { name = "span_id", type = "String" },
      { name = "parent_span_id", type = "String" },
      { name = "trace_state", type = "String" },
      { name = "name", type = "String" },
      { name = "kind", type = "Int32" },
      { name = "flags", type = "Int32" },
      { name = "timestamp", type = "DateTime64(6)" },
      { name = "end_time", type = "DateTime64(6)" },
      { name = "observed_timestamp", type = "DateTime64(6)" },
      { name = "service_name", type = "String" },
      { name = "resource_attributes", type = "Map(LowCardinality(String), String)" },
      { name = "instrumentation_scope", type = "String" },
      { name = "attributes", type = "Map(LowCardinality(String), String)" },
      { name = "dropped_attributes_count", type = "Int32" },
      { name = "events", type = "Array(String)" },
      { name = "dropped_events_count", type = "Int32" },
      { name = "links", type = "Array(String)" },
      { name = "dropped_links_count", type = "Int32" },
      { name = "status_code", type = "Int32" },
      { name = "retention_days", type = "Nullable(Int32)" },
    ]
    settings = { input_format_avro_allow_missing_fields = "1", kafka_num_consumers = "1", kafka_poll_max_batch_size = "1000", kafka_poll_timeout_ms = "3000", kafka_skip_broken_messages = "100", kafka_thread_per_consumer = "1" }
  }
  mv_select = <<-SQL
uuid,
    trace_id,
    span_id,
    parent_span_id,
    trace_state,
    name,
    timestamp,
    end_time,
    observed_timestamp,
    service_name,
    instrumentation_scope,
    events,
    links,
    toInt8(kind) AS kind,
    toUInt32(flags) AS flags,
    toUInt32(dropped_attributes_count) AS dropped_attributes_count,
    toUInt32(dropped_events_count) AS dropped_events_count,
    toUInt32(dropped_links_count) AS dropped_links_count,
    toInt16(status_code) AS status_code,
    mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
    mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
    toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
    observed_timestamp + toIntervalDay(if((retention_days IS NOT NULL) AND (retention_days > 0), retention_days, toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(15)))) AS original_expiry_timestamp,
    _partition,
    _topic,
    _offset,
    toInt64OrDefault(_headers.value[indexOf(_headers.name, 'record_count')], toInt64(1)) AS _record_count,
    toInt64OrDefault(_headers.value[indexOf(_headers.name, 'bytes_uncompressed')], toInt64(0)) AS _bytes_uncompressed,
    toInt64OrDefault(_headers.value[indexOf(_headers.name, 'bytes_compressed')], toInt64(0)) AS _bytes_compressed
  SQL
  mv_target = "${var.database}.trace_spans"
  deployment = merge({
    cluster          = "posthog"
    read_cluster     = "posthog_single_shard"
    kafka_collection = "warpstream_traces"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["trace_spans", "trace_spans_distributed", "kafka_trace_spans_avro_mv", "kafka_trace_spans_avro"], name) }
  })
  names = { storage = "trace_spans", mv = "kafka_trace_spans_avro_mv", kafka = "kafka_trace_spans_avro" }
}

module "trace_spans_kafka_metrics_family" {
  source = "../../lib/table_family"

  name     = "trace_spans_kafka_metrics"
  database = var.database
  layout   = "global"
  columns = [
    { name = "_partition", type = "UInt32" },
    { name = "_topic", type = "String" },
    { name = "max_offset", type = "SimpleAggregateFunction(max, UInt64)" },
    { name = "max_observed_timestamp", type = "SimpleAggregateFunction(max, DateTime64(9))" },
    { name = "max_timestamp", type = "SimpleAggregateFunction(max, DateTime64(9))" },
    { name = "max_created_at", type = "SimpleAggregateFunction(max, DateTime64(9))" },
    { name = "max_lag", type = "SimpleAggregateFunction(max, UInt64)" },
  ]
  storage = {
    order_by = "(_topic, _partition)"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["trace_spans_kafka_metrics"], name) }
  })
}

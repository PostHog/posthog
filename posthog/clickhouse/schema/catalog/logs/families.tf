module "log_attributes_family" {
  source = "../../lib/table_family"

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
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["log_attributes"], name) }
  })
}

module "log_attributes2_family" {
  source = "../../lib/table_family"

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
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["log_attributes2"], name) }
  })
}

module "log_attributes3_family" {
  source = "../../lib/table_family"

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
  sharding_key = ""
  deployment = merge({
    cluster      = "posthog"
    read_cluster = "posthog_single_shard"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["log_attributes3", "log_attributes_distributed"], name) }
  })
  names = { storage = "log_attributes3" }
}

module "logs32_family" {
  source = "../../lib/table_family"

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
  sharding_key = ""
  deployment = merge({
    cluster      = "posthog"
    read_cluster = "posthog_single_shard"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["logs32", "logs"], name) }
  })
  names = { storage = "logs32" }
}

module "logs34_family" {
  source = "../../lib/table_family"

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
    read_columns  = local.logs34_columns
    write_columns = local.logs34_columns
  }
  sharding_key = ""
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
    observed_timestamp + toIntervalDay(if((retention_days IS NOT NULL) AND (retention_days > 0), retention_days, toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(15)))) AS original_expiry_timestamp,
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
    cluster          = "posthog"
    read_cluster     = "posthog_single_shard"
    kafka_collection = "warpstream_logs"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
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
  source = "../../lib/table_family"

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
  sharding_key = ""
  deployment = merge({
    cluster      = "posthog"
    read_cluster = "posthog_single_shard"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["logs_billing_metrics", "logs_billing_metrics_distributed"], name) }
  })
  names = { storage = "logs_billing_metrics" }
}

module "logs_kafka_metrics_family" {
  source = "../../lib/table_family"

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
  sharding_key = ""
  deployment = merge({
    cluster      = "posthog"
    read_cluster = "posthog_single_shard"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["logs_kafka_metrics", "logs_kafka_metrics_distributed"], name) }
  })
  names = { storage = "logs_kafka_metrics" }
}

module "logs_pattern_buckets_family" {
  source = "../../lib/table_family"

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
  sharding_key = ""
  deployment = merge({
    cluster      = "posthog"
    read_cluster = "posthog_single_shard"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["logs_pattern_buckets", "logs_pattern_buckets_distributed"], name) }
  })
  names = { storage = "logs_pattern_buckets" }
}

module "logs_volume_buckets_family" {
  source = "../../lib/table_family"

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
  sharding_key = ""
  deployment = merge({
    cluster      = "posthog"
    read_cluster = "posthog_single_shard"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["logs_volume_buckets", "logs_volume_buckets_distributed"], name) }
  })
  names = { storage = "logs_volume_buckets" }
}

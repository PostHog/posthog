# Kafka tables and the materialized views that consume them.

module "kafka_metrics_avro2" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(local.deployment.exclude, "kafka_metrics_avro2")
  database = var.database
  name     = "kafka_metrics_avro2"
  engine   = "Kafka(warpstream_metrics)"
  settings = "input_format_avro_allow_missing_fields = 1, kafka_format = 'Avro', kafka_group_name = 'clickhouse-metrics-avro2', kafka_num_consumers = 1, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 3000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_metrics'"
  columns  = local.kafka_metrics_avro2_columns
  override = try(local.deployment.overrides["kafka_metrics_avro2"], {})
}

module "kafka_metrics_avro2_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(local.deployment.exclude, "kafka_metrics_avro2_mv")
  database = var.database
  name     = "kafka_metrics_avro2_mv"
  to_table = "${var.database}.metrics2_input"
  query    = <<-SQL
    SELECT
        uuid,
        toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
        ifNull(metric_name, '') AS metric_name,
        reinterpretAsUInt64(assumeNotNull(series_fingerprint)) AS series_fingerprint,
        cityHash64(mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes))) AS resource_fingerprint,
        timestamp,
        observed_timestamp,
        timestamp + toIntervalDay(assumeNotNull(if((retention_days IS NOT NULL) AND (retention_days > 0), retention_days, toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(30))))) AS original_expiry_timestamp,
        ifNull(service_name, '') AS service_name,
        ifNull(metric_type, '') AS metric_type,
        ifNull(value, 0) AS value,
        toUInt64(ifNull(count, 1)) AS count,
        histogram_bounds,
        arrayMap(x -> toUInt64(x), histogram_counts) AS histogram_counts,
        trace_id,
        span_id,
        ifNull(trace_flags, 0) AS trace_flags,
        toBool(ifNull(has_labels, 1)) AS has_labels,
        ifNull(unit, '') AS unit,
        ifNull(aggregation_temporality, '') AS aggregation_temporality,
        ifNull(is_monotonic, 0) AS is_monotonic,
        ifNull(instrumentation_scope, '') AS instrumentation_scope,
        if(toBool(ifNull(has_labels, 1)), mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)), CAST(map(), 'Map(String, String)')) AS resource_attributes,
        if(toBool(ifNull(has_labels, 1)), mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), attributes)), CAST(map(), 'Map(String, String)')) AS attributes,
        _partition,
        _topic,
        _offset
    FROM ${var.database}.kafka_metrics_avro2
    WHERE kafka_metrics_avro2.series_fingerprint IS NOT NULL
    SETTINGS min_insert_block_size_rows = 0, min_insert_block_size_bytes = 0
  SQL
  override = try(local.deployment.overrides["kafka_metrics_avro2_mv"], {})

  depends_on = [
    module.kafka_metrics_avro2,
    module.metrics2_input,
  ]
}

module "kafka_metrics_avro4" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(local.deployment.exclude, "kafka_metrics_avro4")
  database = var.database
  name     = "kafka_metrics_avro4"
  engine   = "Kafka(warpstream_metrics)"
  settings = "input_format_avro_allow_missing_fields = 1, kafka_format = 'Avro', kafka_group_name = 'clickhouse-metrics-avro4', kafka_num_consumers = 1, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 3000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_metrics'"
  columns  = local.kafka_metrics_avro2_columns
  override = try(local.deployment.overrides["kafka_metrics_avro4"], {})
}

module "kafka_metrics_avro4_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(local.deployment.exclude, "kafka_metrics_avro4_mv")
  database = var.database
  name     = "kafka_metrics_avro4_mv"
  to_table = "${var.database}.metrics4_input"
  query    = <<-SQL
    SELECT
        uuid,
        toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
        ifNull(metric_name, '') AS metric_name,
        reinterpretAsUInt64(assumeNotNull(series_fingerprint)) AS series_fingerprint,
        cityHash64(mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes))) AS resource_fingerprint,
        timestamp,
        observed_timestamp,
        timestamp + toIntervalDay(assumeNotNull(if((retention_days IS NOT NULL) AND (retention_days > 0), retention_days, toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(30))))) AS original_expiry_timestamp,
        ifNull(service_name, '') AS service_name,
        ifNull(metric_type, '') AS metric_type,
        ifNull(value, 0) AS value,
        toUInt64(ifNull(count, 1)) AS count,
        histogram_bounds,
        arrayMap(x -> toUInt64(x), histogram_counts) AS histogram_counts,
        trace_id,
        span_id,
        ifNull(trace_flags, 0) AS trace_flags,
        toBool(ifNull(has_labels, 1)) AS has_labels,
        ifNull(unit, '') AS unit,
        ifNull(aggregation_temporality, '') AS aggregation_temporality,
        ifNull(is_monotonic, 0) AS is_monotonic,
        ifNull(instrumentation_scope, '') AS instrumentation_scope,
        if(toBool(ifNull(has_labels, 1)), mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)), CAST(map(), 'Map(String, String)')) AS resource_attributes,
        if(toBool(ifNull(has_labels, 1)), mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), attributes)), CAST(map(), 'Map(String, String)')) AS attributes,
        _partition,
        _topic,
        _offset
    FROM ${var.database}.kafka_metrics_avro4
    WHERE kafka_metrics_avro4.series_fingerprint IS NOT NULL
    SETTINGS min_insert_block_size_rows = 0, min_insert_block_size_bytes = 0
  SQL
  override = try(local.deployment.overrides["kafka_metrics_avro4_mv"], {})

  depends_on = [
    module.kafka_metrics_avro4,
    module.metrics4_input,
  ]
}

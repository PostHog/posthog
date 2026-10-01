# Kafka tables and the materialized views that consume them.

module "kafka_logs34_avro_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "kafka_logs34_avro_mv")
  database = var.database
  name     = "kafka_logs34_avro_mv"
  to_table = "${var.database}.writable_logs34"
  query    = <<-SQL
    SELECT
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
    FROM ${var.database}.kafka_logs_avro
  SQL
  override = try(var.overrides["kafka_logs34_avro_mv"], {})

  depends_on = [
    module.kafka_logs_avro,
    module.writable_logs34,
  ]
}

module "kafka_logs_avro" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_logs_avro")
  database = var.database
  name     = "kafka_logs_avro"
  engine   = "Kafka(warpstream_logs)"
  settings = "input_format_avro_allow_missing_fields = 1, kafka_format = 'Avro', kafka_group_name = 'clickhouse-logs-avro-new', kafka_num_consumers = 1, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 3000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_logs'"
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
  override = try(var.overrides["kafka_logs_avro"], {})
}

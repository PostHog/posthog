# Kafka tables and the materialized views that consume them.

module "kafka_trace_spans_avro" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_trace_spans_avro")
  database = var.database
  name     = "kafka_trace_spans_avro"
  engine   = "Kafka(warpstream_traces)"
  settings = "input_format_avro_allow_missing_fields = 1, kafka_format = 'Avro', kafka_group_name = 'clickhouse-traces-avro', kafka_num_consumers = 1, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 3000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_traces'"
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
  override = try(var.overrides["kafka_trace_spans_avro"], {})
}

module "kafka_trace_spans_avro_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "kafka_trace_spans_avro_mv")
  database = var.database
  name     = "kafka_trace_spans_avro_mv"
  to_table = "${var.database}.trace_spans"
  query    = <<-SQL
    SELECT
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
    FROM ${var.database}.kafka_trace_spans_avro
  SQL
  override = try(var.overrides["kafka_trace_spans_avro_mv"], {})

  depends_on = [
    module.kafka_trace_spans_avro,
    module.trace_spans,
  ]
}

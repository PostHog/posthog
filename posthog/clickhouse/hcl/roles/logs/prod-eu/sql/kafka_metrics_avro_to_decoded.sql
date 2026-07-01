SELECT
  toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
  ifNull(metric_name, '') AS metric_name,
  cityHash64(
    ifNull(metric_name, ''),
    ifNull(service_name, ''),
    mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)),
    mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), attributes))
  ) AS series_fingerprint,
  ifNull(metric_type, '') AS metric_type,
  ifNull(unit, '') AS unit,
  ifNull(service_name, '') AS service_name,
  mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
  mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), attributes)) AS attributes,
  timestamp,
  ifNull(value, 0) AS value,
  trace_id,
  span_id,
  ifNull(trace_flags, 0) AS trace_flags
FROM posthog.kafka_metrics_avro
SETTINGS
  min_insert_block_size_rows = 0,
  min_insert_block_size_bytes = 0

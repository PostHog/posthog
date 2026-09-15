SELECT
  uuid,
  toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
  ifNull(metric_name, '') AS metric_name,
  reinterpretAsUInt64(assumeNotNull(series_fingerprint)) AS series_fingerprint,
  cityHash64(mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes))) AS resource_fingerprint,
  timestamp,
  observed_timestamp,
  observed_timestamp + toIntervalDay(assumeNotNull(if((retention_days IS NOT NULL) AND (retention_days > 0), retention_days, toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(90))))) AS original_expiry_timestamp,
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
FROM posthog.kafka_metrics_avro2
WHERE kafka_metrics_avro2.series_fingerprint IS NOT NULL
SETTINGS
  min_insert_block_size_rows = 0,
  min_insert_block_size_bytes = 0

SELECT
  uuid,
  trace_id,
  span_id,
  ifNull(trace_flags, 0) AS trace_flags,
  timestamp,
  observed_timestamp,
  ifNull(service_name, '') AS service_name,
  ifNull(metric_name, '') AS metric_name,
  ifNull(metric_type, '') AS metric_type,
  ifNull(value, 0) AS value,
  toUInt64(ifNull(count, 1)) AS count,
  histogram_bounds,
  arrayMap(x -> toUInt64(x), histogram_counts) AS histogram_counts,
  ifNull(unit, '') AS unit,
  ifNull(aggregation_temporality, '') AS aggregation_temporality,
  ifNull(is_monotonic, 0) AS is_monotonic,
  mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
  ifNull(instrumentation_scope, '') AS instrumentation_scope,
  mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
  mapSort(
    mapFilter(
      (k, v) -> isNotNull(v),
      mapApply(
        (k, v) -> (concat(k, '__float'), toFloat64OrNull(JSONExtract(v, 'String'))),
        attributes
      )
    )
  ) AS attributes_map_float,
  toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id
FROM posthog.kafka_metrics_avro
SETTINGS
  min_insert_block_size_rows = 0,
  min_insert_block_size_bytes = 0

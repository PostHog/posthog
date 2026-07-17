SELECT
  * EXCEPT(attributes, resource_attributes, kind, flags, dropped_attributes_count, dropped_events_count, dropped_links_count, status_code),
  toInt8(kind) AS kind,
  toUInt32(flags) AS flags,
  toUInt32(dropped_attributes_count) AS dropped_attributes_count,
  toUInt32(dropped_events_count) AS dropped_events_count,
  toUInt32(dropped_links_count) AS dropped_links_count,
  toInt16(status_code) AS status_code,
  mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
  mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
  toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
  _partition,
  _topic,
  _offset,
  toInt64OrDefault(_headers.value[indexOf(_headers.name, 'record_count')], toInt64(1)) AS _record_count,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_uncompressed')]) AS _bytes_uncompressed,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_compressed')]) AS _bytes_compressed
FROM posthog.kafka_trace_spans_avro

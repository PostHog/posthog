SELECT
  kafka_logs_avro.* EXCEPT(created_at, attribute_values, attribute_keys, attributes, attributes_map_str, attributes_map_float, attributes_map_datetime, resource_attributes),
  mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
  mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
  toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
  observed_timestamp
  + toIntervalDay(
    toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(15))
  ) AS original_expiry_timestamp,
  _partition,
  _topic,
  _offset,
  toInt64OrDefault(_headers.value[indexOf(_headers.name, 'record_count')], toInt64(1)) AS _record_count,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_uncompressed')]) / _record_count AS _bytes_uncompressed,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_compressed')]) / _record_count AS _bytes_compressed
FROM posthog.kafka_logs_avro

SELECT
  kafka_partition AS _partition,
  kafka_topic AS _topic,
  maxSimpleState(kafka_offset) AS max_offset,
  maxSimpleState(observed_timestamp) AS max_observed_timestamp,
  maxSimpleState(timestamp) AS max_timestamp,
  maxSimpleState(now()) AS max_created_at,
  maxSimpleState(now() - observed_timestamp) AS max_lag
FROM
  (
    SELECT
      kafka_source.1 AS kafka_topic,
      kafka_source.2 AS kafka_partition,
      kafka_source.3 AS kafka_offset,
      observed_timestamp,
      timestamp
    FROM posthog.logs34
    ARRAY JOIN [(_topic, _partition, _offset), (_source_topic, _source_partition, 0)] AS kafka_source
    WHERE kafka_topic != ''
  )
GROUP BY
  kafka_partition, kafka_topic

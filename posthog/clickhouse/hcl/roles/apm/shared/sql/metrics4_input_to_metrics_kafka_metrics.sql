SELECT
  _partition,
  _topic,
  maxSimpleState(_offset) AS max_offset,
  maxSimpleState(observed_timestamp) AS max_observed_timestamp,
  maxSimpleState(timestamp) AS max_timestamp,
  maxSimpleState(now()) AS max_created_at,
  maxSimpleState(toUInt64(greatest(dateDiff('second', observed_timestamp, now()), 0))) AS max_lag
FROM posthog.metrics4_input
GROUP BY
  _partition, _topic

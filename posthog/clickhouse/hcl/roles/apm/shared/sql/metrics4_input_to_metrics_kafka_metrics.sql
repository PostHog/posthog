SELECT
  _partition,
  _topic,
  maxSimpleState(_offset) AS max_offset,
  maxSimpleState(observed_timestamp) AS max_observed_timestamp,
  maxSimpleState(now()) AS max_created_at
FROM posthog.metrics4_input
GROUP BY
  _partition, _topic

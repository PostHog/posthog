SELECT
  team_id,
  toStartOfHour(timestamp) AS time_bucket,
  service_name,
  toStartOfHour(original_expiry_timestamp) AS original_expiry_time_bucket,
  maxSimpleState(timestamp) AS max_timestamp
FROM posthog.metrics4_input
GROUP BY
  team_id, time_bucket, service_name, original_expiry_time_bucket

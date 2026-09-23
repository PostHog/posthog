SELECT
  team_id,
  metric_name,
  toStartOfHour(timestamp) AS time_bucket,
  toStartOfHour(input.original_expiry_timestamp) AS original_expiry_time_bucket,
  maxSimpleState(input.original_expiry_timestamp) AS original_expiry_timestamp
FROM posthog.metrics4_input AS input
WHERE has_labels
GROUP BY
  team_id, time_bucket, metric_name, original_expiry_time_bucket

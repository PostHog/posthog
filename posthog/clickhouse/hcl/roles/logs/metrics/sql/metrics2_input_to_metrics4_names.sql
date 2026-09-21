SELECT
  team_id,
  metric_name,
  toStartOfHour(timestamp) AS time_bucket,
  toStartOfHour(
    timestamp + toIntervalDay(if(retention_days_explicit > 0, retention_days_explicit, toInt32(30)))
  ) AS original_expiry_time_bucket,
  maxSimpleState(
    timestamp + toIntervalDay(if(retention_days_explicit > 0, retention_days_explicit, toInt32(30)))
  ) AS original_expiry_timestamp
FROM posthog.metrics2_input
WHERE has_labels
GROUP BY
  team_id, time_bucket, metric_name, original_expiry_time_bucket

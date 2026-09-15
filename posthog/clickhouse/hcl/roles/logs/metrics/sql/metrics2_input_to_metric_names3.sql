SELECT
    team_id,
    metric_name,
    toStartOfHour(timestamp) AS time_bucket,
    maxSimpleState(original_expiry_timestamp) AS original_expiry_timestamp
FROM posthog.metrics2_input
WHERE has_labels
GROUP BY team_id, time_bucket, metric_name

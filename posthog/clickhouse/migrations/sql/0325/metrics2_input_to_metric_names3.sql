CREATE MATERIALIZED VIEW IF NOT EXISTS posthog.metrics2_input_to_metric_names3 TO posthog.writable_metric_names3 (team_id Int32, metric_name LowCardinality(String), time_bucket DateTime64(0), original_expiry_time_bucket DateTime64(0), original_expiry_timestamp SimpleAggregateFunction(max, DateTime64(6))) AS SELECT
  team_id,
  metric_name,
  toStartOfHour(timestamp) AS time_bucket,
  toStartOfHour(input.original_expiry_timestamp) AS original_expiry_time_bucket,
  maxSimpleState(input.original_expiry_timestamp) AS original_expiry_timestamp
FROM posthog.metrics2_input AS input
WHERE has_labels
GROUP BY
  team_id, time_bucket, metric_name, original_expiry_time_bucket;

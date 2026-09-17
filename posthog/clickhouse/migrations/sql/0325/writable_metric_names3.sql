CREATE TABLE IF NOT EXISTS posthog.writable_metric_names3 (
  team_id Int32,
  metric_name LowCardinality(String),
  time_bucket DateTime64(0),
  original_expiry_time_bucket DateTime64(0),
  original_expiry_timestamp SimpleAggregateFunction(max, DateTime64(6))
) ENGINE = Distributed('logs', 'posthog', 'metric_names3');

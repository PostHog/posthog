CREATE TABLE IF NOT EXISTS posthog.writable_metric_attributes2 (
  team_id Int32,
  time_bucket DateTime64(0),
  original_expiry_time_bucket DateTime64(0),
  service_name LowCardinality(String),
  attribute_key LowCardinality(String),
  attribute_value String,
  attribute_type LowCardinality(String),
  attribute_count SimpleAggregateFunction(sum, UInt64)
) ENGINE = Distributed('logs', 'posthog', 'metric_attributes2');

CREATE TABLE IF NOT EXISTS posthog.writable_metric_series3 (
  team_id Int32,
  metric_name LowCardinality(String),
  series_fingerprint UInt64,
  metric_type LowCardinality(String),
  unit LowCardinality(String),
  aggregation_temporality LowCardinality(String),
  is_monotonic Bool DEFAULT false,
  service_name LowCardinality(String),
  instrumentation_scope String,
  resource_attributes Map(LowCardinality(String), String),
  resource_fingerprint UInt64 MATERIALIZED cityHash64(resource_attributes),
  attributes Map(LowCardinality(String), String),
  last_seen DateTime64(6),
  original_expiry_timestamp DateTime64(6)
) ENGINE = Distributed('logs', 'posthog', 'metric_series3');

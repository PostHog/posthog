CREATE MATERIALIZED VIEW IF NOT EXISTS posthog.metrics2_input_to_metric_series3 TO posthog.writable_metric_series3 (team_id Int32, metric_name LowCardinality(String), series_fingerprint UInt64, metric_type LowCardinality(String), unit LowCardinality(String), aggregation_temporality LowCardinality(String), is_monotonic Bool, service_name LowCardinality(String), instrumentation_scope String, resource_attributes Map(LowCardinality(String), String), attributes Map(LowCardinality(String), String), last_seen DateTime64(6), original_expiry_timestamp DateTime64(6)) AS SELECT
  team_id,
  metric_name,
  series_fingerprint,
  metric_type,
  unit,
  aggregation_temporality,
  is_monotonic,
  service_name,
  instrumentation_scope,
  resource_attributes,
  attributes,
  timestamp AS last_seen,
  original_expiry_timestamp
FROM posthog.metrics2_input
WHERE has_labels;

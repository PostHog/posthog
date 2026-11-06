SELECT
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
  timestamp,
  original_expiry_timestamp
FROM posthog.metrics4_input
WHERE has_labels

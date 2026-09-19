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
  timestamp + toIntervalDay(if(retention_days_explicit > 0, retention_days_explicit, toInt32(30))) AS original_expiry_timestamp
FROM posthog.metrics2_input
WHERE has_labels

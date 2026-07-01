SELECT
  team_id,
  metric_name,
  series_fingerprint,
  metric_type,
  unit,
  service_name,
  resource_attributes,
  attributes,
  timestamp AS last_seen
FROM posthog.metric_events_decoded

SELECT
  team_id,
  metric_name,
  series_fingerprint,
  timestamp,
  value,
  trace_id,
  span_id,
  trace_flags
FROM posthog.metric_events_decoded

SELECT
  team_id,
  property_type,
  property_key,
  property_value,
  property_count,
  coalesce(_timestamp, now()) AS last_seen
FROM posthog.kafka_property_values

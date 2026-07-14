SELECT
  team_id,
  property_type,
  property_key,
  property_value,
  toDate(now()) AS day
FROM posthog.kafka_property_values_daily

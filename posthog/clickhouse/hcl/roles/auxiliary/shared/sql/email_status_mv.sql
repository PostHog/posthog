SELECT
  team_id,
  message_id,
  status,
  version,
  created_at,
  status_at,
  reason,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_email_status

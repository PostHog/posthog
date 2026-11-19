SELECT
  team_id,
  message_id,
  status,
  version,
  created_at,
  status_at,
  reason,
  recipient,
  function_id,
  sending_domain,
  scheduled_at,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_email_status_events

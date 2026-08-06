SELECT
  team_id,
  fingerprint,
  issue_id,
  issue_name,
  issue_description,
  issue_status,
  assigned_user_id,
  assigned_role_id,
  first_seen,
  is_deleted,
  version,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_error_tracking_fingerprint_issue_state

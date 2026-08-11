SELECT
  team_id,
  time_bucket,
  original_expiry_time_bucket,
  service_name,
  resource_fingerprint,
  attribute_key,
  attribute_value,
  attribute_type,
  severity_text,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
      toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
      service_name AS service_name,
      resource_fingerprint,
      severity_text AS severity_text,
      arrayJoin(resource_attributes) AS attribute,
      'resource' AS attribute_type,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.logs34
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, severity_text, resource_attributes
  )

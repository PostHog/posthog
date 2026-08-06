SELECT
  team_id,
  original_expiry_time_bucket,
  time_bucket,
  service_name,
  resource_fingerprint,
  attribute_key,
  attribute_value,
  'span_resource_attribute' AS attribute_type,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
      toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
      service_name AS service_name,
      resource_fingerprint,
      arrayJoin(resource_attributes) AS attribute,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.trace_spans
    GROUP BY
      team_id, original_expiry_time_bucket, time_bucket, service_name, resource_fingerprint, attribute
  )

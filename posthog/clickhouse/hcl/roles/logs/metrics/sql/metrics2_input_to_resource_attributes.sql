SELECT
  team_id,
  time_bucket,
  original_expiry_time_bucket,
  service_name,
  attribute_key,
  attribute_value,
  attribute_type,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
      toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
      service_name AS service_name,
      resource_attributes AS filtered_attributes,
      arrayJoin(filtered_attributes) AS attribute,
      'resource' AS attribute_type,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.metrics2_input
    WHERE has_labels
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, filtered_attributes
  )

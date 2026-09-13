SELECT
  team_id,
  time_bucket,
  service_name,
  resource_fingerprint,
  attribute_key,
  attribute_value,
  attribute_type,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
      service_name AS service_name,
      resource_fingerprint,
      mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
      arrayJoin(attributes) AS attribute,
      'metric' AS attribute_type,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.metrics1
    GROUP BY
      team_id, time_bucket, service_name, resource_fingerprint, attributes
  )

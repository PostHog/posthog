SELECT
  team_id,
  time_bucket,
  service_name,
  sumSimpleState(_bytes_uncompressed) AS bytes_uncompressed,
  sumSimpleState(_bytes_compressed) AS bytes_compressed,
  sumSimpleState(1) AS record_count
FROM
  (
    SELECT
      team_id,
      toStartOfInterval(timestamp, toIntervalMinute(1)) AS time_bucket,
      service_name AS service_name,
      _record_count,
      _bytes_uncompressed,
      _bytes_compressed
    FROM posthog.logs34
  )
GROUP BY
  team_id, time_bucket, service_name

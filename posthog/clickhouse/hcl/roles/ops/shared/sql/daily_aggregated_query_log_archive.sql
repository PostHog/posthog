SELECT
  event_date AS day,
  team_id,
  user,
  current_database,
  query_kind,
  lc_kind,
  lc_access_method,
  lc_query_type,
  lc_product,
  lc_name,
  lc_feature,
  lc_query__kind,
  lc_api_key_label,
  count() AS query_count,
  sum(read_bytes) AS read_bytes,
  sum(read_rows) AS read_rows,
  sum(query_duration_ms) AS query_duration_ms,
  sum(ProfileEvents_OSCPUVirtualTimeMicroseconds) AS cpu_microseconds,
  countIf(exception_code != 0) AS error_count,
  countIf(exception_code IN (159, 160, 241)) AS timeout_oom_count
FROM posthog.sharded_query_log_archive
WHERE
  is_initial_query
AND
  (event_date < today())
GROUP BY
  day, team_id, user, current_database, query_kind, lc_kind, lc_access_method, lc_query_type, lc_product, lc_name, lc_feature, lc_query__kind, lc_api_key_label

SELECT
  'ClickHouseCustomMetric_ServerCrash' AS name,
  map('instance', hostname()) AS labels,
  count() AS value,
  'Number of server crashes for current date' AS help,
  'gauge' AS type
FROM system.crash_log
WHERE event_date = today()
GROUP BY
  hostname()

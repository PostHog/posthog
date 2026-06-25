# Shared: invariant custom_metrics_* sub-views (identical on every role). The custom_metrics aggregator is role-specific (see roles/ops).

database "posthog" {
  view "custom_metrics_backups" {
    query = "WITH ['ClickHouseCustomMetric_BackupFailed', 'ClickHouseCustomMetric_BackupSuccess', 'ClickHouseCustomMetric_BackupCancelled', 'ClickHouseCustomMetric_BackupAttempts'] AS names, [toInt64(countIf(status = 'BACKUP_FAILED')), toInt64(countIf(status = 'BACKUP_CREATED')), toInt64(countIf(status = 'BACKUP_CANCELLED')), toInt64(countIf(status = 'CREATING_BACKUP'))] AS values, ['Number of failed backups', 'Number of successful backups', 'Number of cancelled backups', 'Number of backup attempts'] AS descriptions, ['gauge', 'gauge', 'gauge', 'gauge'] AS types, arrayJoin(arrayZip(names, values, descriptions, types)) AS tpl SELECT tpl.1 AS name, map('instance', hostname()) AS labels, tpl.2 AS value, tpl.3 AS help, tpl.4 AS type FROM system.backup_log WHERE event_date = today() GROUP BY event_date"
  }
  view "custom_metrics_dictionaries" {
    query = "SELECT 'ClickHouseCustomMetric_DictionariesFailed' AS name, map('instance', hostname(), 'database', d.database, 'dictionary', d.dict_name, 'uuid', toString(d.uuid), 'status', toString(d.status)) AS labels, toUInt64(1) AS value, 'Dictionary is in FAILED or FAILED_AND_RELOADING status' AS help, 'gauge' AS type FROM (SELECT name AS dict_name, database, uuid, status FROM system.dictionaries WHERE status IN ('FAILED', 'FAILED_AND_RELOADING')) AS d"
  }
  view "custom_metrics_part_counts" {
    query = "SELECT 'ClickHouseCustomMetric_MaxPartCountPerPartition' AS name, map('instance', hostname(), 'database', database, 'table', `table`, 'partition', partition) AS labels, part_count AS value, 'Maximum number of active parts for any partition in a PostHog table' AS help, 'gauge' AS type FROM (SELECT database, `table`, partition, count() AS part_count FROM system.parts WHERE active AND (database = 'posthog') GROUP BY database, `table`, partition ORDER BY database ASC, `table` ASC, part_count DESC, partition ASC LIMIT 1 BY database, `table`)"
  }
  view "custom_metrics_replication_queue" {
    query = "WITH ['ClickHouseCustomMetric_ReplicationQueueStuckEntries', 'ClickHouseCustomMetric_ReplicationQueueMaxPostponedEntrySeconds', 'ClickHouseCustomMetric_ReplicationQueueMaxErrorEntrySeconds'] AS names, [toInt64(countIf(create_time < (now() - toIntervalDay(15)))), maxIf(dateDiff('seconds', create_time, last_postpone_time), last_postpone_time != '1970-01-01'), maxIf(dateDiff('seconds', create_time, last_exception_time), (last_exception_time != '1970-01-01') AND (last_exception_time > (now() - toIntervalMinute(5))))] AS values, ['Number of entries that have been in the replication queue for more than 15 days', 'Maximum number of seconds that an entry has been postponed', 'Maximum number of seconds that an entry has been in error'] AS descriptions, ['gauge', 'gauge', 'gauge'] AS types, arrayJoin(arrayZip(names, values, descriptions, types)) AS tpl SELECT tpl.1 AS name, map('table', `table`, 'instance', hostname()) AS labels, tpl.2 AS value, tpl.3 AS help, tpl.4 AS type FROM system.replication_queue GROUP BY `table` HAVING value > 0"
  }
  view "custom_metrics_server_crash" {
    query = "SELECT 'ClickHouseCustomMetric_ServerCrash' AS name, map('instance', hostname()) AS labels, count() AS value, 'Number of server crashes for current date' AS help, 'gauge' AS type FROM system.crash_log WHERE event_date = today() GROUP BY hostname()"
  }
  view "custom_metrics_table_sizes" {
    query = "SELECT 'ClickHouseCustomMetric_TableTotalBytes' AS name, map('instance', hostname(), 'database', database, 'table', `table`) AS labels, CAST(total_bytes, 'Float64') AS value, 'Size of a database table on a given node (need a sum for sharded)' AS help, 'gauge' AS type FROM system.tables WHERE (database NOT IN ('INFORMATION_SCHEMA', 'information_schema')) AND (total_bytes IS NOT NULL)"
  }
  view "custom_metrics_test" {
    query = "SELECT 'ClickHouseCustomMetric_Test' AS name, map('instance', hostname()) AS labels, 1 AS value, 'Test to check that the metric endpoint is working' AS help, 'gauge' AS type"
  }
}

variable "node" {
  description = "The server these objects live on: { name, host, port, leader }. Null puts them on the provider's host."
  type        = any
  default     = null
}

variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "objects" {
  description = "Names of the objects to create."
  type        = set(string)
}

variable "test" {
  description = "Use the definitions the test suite expects."
  type        = bool
  default     = false
}

variable "deployment" { type = any }

locals {
  deployment = merge({ overrides = {} }, var.deployment)
}

locals {
}

# Distributed tables, views and dictionaries that queries read from.

module "custom_metrics" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "custom_metrics")
  database = var.database
  name     = "custom_metrics"
  query    = <<-SQL
    SELECT * REPLACE (toFloat64(value) AS value)
    FROM ${var.database}.custom_metrics_test
    UNION ALL
    SELECT * REPLACE (toFloat64(value) AS value)
    FROM ${var.database}.custom_metrics_replication_queue
    UNION ALL
    SELECT * REPLACE (toFloat64(value) AS value)
    FROM ${var.database}.custom_metrics_server_crash
    UNION ALL
    SELECT *
    FROM ${var.database}.custom_metrics_table_sizes
    UNION ALL
    SELECT * REPLACE (toFloat64(value) AS value)
    FROM ${var.database}.custom_metrics_part_counts
    UNION ALL
    SELECT * REPLACE (toFloat64(value) AS value)
    FROM ${var.database}.custom_metrics_dictionaries
    UNION ALL
    SELECT
        'ClickHouseCustomMetric_S3DiskBytesUsed' AS name,
        map('instance', hostname(), 'disk', disk_name) AS labels,
        toFloat64(sum(bytes_on_disk)) AS value,
        'Bytes currently used by ClickHouse parts on S3-backed disks on this node' AS help,
        'gauge' AS type
    FROM system.parts
    WHERE disk_name IN ('s3disk', 'cache')
    GROUP BY disk_name
    UNION ALL
    SELECT
        'ClickHouseCustomMetric_MergeFailures15m' AS name,
        map('instance', hostname()) AS labels,
        toFloat64(count()) AS value,
        'Number of failed merge operations in the last 15 minutes' AS help,
        'gauge' AS type
    FROM system.part_log
    WHERE (event_time >= (now() - toIntervalMinute(15))) AND (event_type = 'MergeParts') AND (error > 0) AND (merge_reason != 'NotAMerge') AND (error != 40)
    UNION ALL
    SELECT
        'ClickHouseCustomMetric_MergeRetriesMaxPerTable15m' AS name,
        map('instance', hostname()) AS labels,
        toFloat64(max(cnt)) AS value,
        'Max failed merge retries for any single table in the last 15 minutes' AS help,
        'gauge' AS type
    FROM
    (
        SELECT count() AS cnt
        FROM system.part_log
        WHERE (event_time >= (now() - toIntervalMinute(15))) AND (event_type = 'MergeParts') AND (error > 0) AND (merge_reason != 'NotAMerge') AND (error != 40)
        GROUP BY
            database,
            `table`,
            partition_id
    )
    ${var.test ? "UNION ALL SELECT * FROM ${var.database}.custom_metrics_counters" : ""}
  SQL
  override = try(local.deployment.overrides["custom_metrics"], {})

  depends_on = [
    module.custom_metrics_counters,
    module.custom_metrics_dictionaries,
    module.custom_metrics_part_counts,
    module.custom_metrics_replication_queue,
    module.custom_metrics_server_crash,
    module.custom_metrics_table_sizes,
    module.custom_metrics_test,
  ]
}

module "custom_metrics_backups" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "custom_metrics_backups")
  database = var.database
  name     = "custom_metrics_backups"
  query    = <<-SQL
    WITH
        ['ClickHouseCustomMetric_BackupFailed', 'ClickHouseCustomMetric_BackupSuccess', 'ClickHouseCustomMetric_BackupCancelled', 'ClickHouseCustomMetric_BackupAttempts'] AS names,
        [toInt64(countIf(status = 'BACKUP_FAILED')), toInt64(countIf(status = 'BACKUP_CREATED')), toInt64(countIf(status = 'BACKUP_CANCELLED')), toInt64(countIf(status = 'CREATING_BACKUP'))] AS `values`,
        ['Number of failed backups', 'Number of successful backups', 'Number of cancelled backups', 'Number of backup attempts'] AS descriptions,
        ['gauge', 'gauge', 'gauge', 'gauge'] AS types,
        arrayJoin(arrayZip(names, `values`, descriptions, types)) AS tpl
    SELECT
        tpl.1 AS name,
        map('instance', hostname()) AS labels,
        tpl.2 AS value,
        tpl.3 AS help,
        tpl.4 AS type
    FROM system.backup_log
    WHERE event_date = today()
    GROUP BY event_date
  SQL
  override = try(local.deployment.overrides["custom_metrics_backups"], {})
}

module "custom_metrics_dictionaries" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "custom_metrics_dictionaries")
  database = var.database
  name     = "custom_metrics_dictionaries"
  query    = <<-SQL
    SELECT
        'ClickHouseCustomMetric_DictionariesFailed' AS name,
        map('instance', hostname(), 'database', d.database, 'dictionary', d.dict_name, 'uuid', toString(d.uuid), 'status', toString(d.status)) AS labels,
        toUInt64(1) AS value,
        'Dictionary is in FAILED or FAILED_AND_RELOADING status' AS help,
        'gauge' AS type
    FROM
    (
        SELECT
            name AS dict_name,
            database,
            uuid,
            status
        FROM system.dictionaries
        WHERE status IN ('FAILED', 'FAILED_AND_RELOADING')
    ) AS d
  SQL
  override = try(local.deployment.overrides["custom_metrics_dictionaries"], {})
}

module "custom_metrics_part_counts" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "custom_metrics_part_counts")
  database = var.database
  name     = "custom_metrics_part_counts"
  query    = <<-SQL
    SELECT
        'ClickHouseCustomMetric_MaxPartCountPerPartition' AS name,
        map('instance', hostname(), 'database', database, 'table', `table`, 'partition', partition) AS labels,
        part_count AS value,
        'Maximum number of active parts for any partition in a PostHog table' AS help,
        'gauge' AS type
    FROM
    (
        SELECT
            database,
            `table`,
            partition,
            count() AS part_count
        FROM system.parts
        WHERE active AND (database = 'posthog')
        GROUP BY
            database,
            `table`,
            partition
        ORDER BY
            database ASC,
            `table` ASC,
            part_count DESC,
            partition ASC
        LIMIT 1 BY
            database,
            `table`
    )
  SQL
  override = try(local.deployment.overrides["custom_metrics_part_counts"], {})
}

module "custom_metrics_replication_queue" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "custom_metrics_replication_queue")
  database = var.database
  name     = "custom_metrics_replication_queue"
  query    = <<-SQL
    WITH
        ['ClickHouseCustomMetric_ReplicationQueueStuckEntries', 'ClickHouseCustomMetric_ReplicationQueueMaxPostponedEntrySeconds', 'ClickHouseCustomMetric_ReplicationQueueMaxErrorEntrySeconds'] AS names,
        [toInt64(countIf(create_time < (now() - toIntervalDay(15)))), maxIf(dateDiff('seconds', create_time, last_postpone_time), last_postpone_time != '1970-01-01'), maxIf(dateDiff('seconds', create_time, last_exception_time), (last_exception_time != '1970-01-01') AND (last_exception_time > (now() - toIntervalMinute(5))))] AS `values`,
        ['Number of entries that have been in the replication queue for more than 15 days', 'Maximum number of seconds that an entry has been postponed', 'Maximum number of seconds that an entry has been in error'] AS descriptions,
        ['gauge', 'gauge', 'gauge'] AS types,
        arrayJoin(arrayZip(names, `values`, descriptions, types)) AS tpl
    SELECT
        tpl.1 AS name,
        map('table', `table`, 'instance', hostname()) AS labels,
        tpl.2 AS value,
        tpl.3 AS help,
        tpl.4 AS type
    FROM system.replication_queue
    GROUP BY `table`
    HAVING value > 0
  SQL
  override = try(local.deployment.overrides["custom_metrics_replication_queue"], {})
}

module "custom_metrics_server_crash" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "custom_metrics_server_crash")
  database = var.database
  name     = "custom_metrics_server_crash"
  query    = <<-SQL
    SELECT
        'ClickHouseCustomMetric_ServerCrash' AS name,
        map('instance', hostname()) AS labels,
        count() AS value,
        'Number of server crashes for current date' AS help,
        'gauge' AS type
    FROM system.crash_log
    WHERE event_date = today()
    GROUP BY hostname()
  SQL
  override = try(local.deployment.overrides["custom_metrics_server_crash"], {})
}

module "custom_metrics_table_sizes" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "custom_metrics_table_sizes")
  database = var.database
  name     = "custom_metrics_table_sizes"
  query    = <<-SQL
    SELECT
        'ClickHouseCustomMetric_TableTotalBytes' AS name,
        map('instance', hostname(), 'database', database, 'table', `table`) AS labels,
        CAST(total_bytes, 'Float64') AS value,
        'Size of a database table on a given node (need a sum for sharded)' AS help,
        'gauge' AS type
    FROM system.tables
    WHERE (database NOT IN ('INFORMATION_SCHEMA', 'information_schema')) AND (total_bytes IS NOT NULL)
  SQL
  override = try(local.deployment.overrides["custom_metrics_table_sizes"], {})
}

module "custom_metrics_test" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "custom_metrics_test")
  database = var.database
  name     = "custom_metrics_test"
  query    = <<-SQL
    SELECT
        'ClickHouseCustomMetric_Test' AS name,
        map('instance', hostname()) AS labels,
        1 AS value,
        'Test to check that the metric endpoint is working' AS help,
        'gauge' AS type
  SQL
  override = try(local.deployment.overrides["custom_metrics_test"], {})
}

module "custom_metrics_counter_events" {
  source = "../../lib/table"
  node   = var.node

  enabled      = contains(var.objects, "custom_metrics_counter_events")
  database     = var.database
  name         = "custom_metrics_counter_events"
  engine       = "ReplicatedMergeTree('${coalesce(lookup(local.deployment, "keeper_path", null), "/clickhouse/tables/noshard/${var.database}.metrics_counter_events")}', '{replica}-{shard}')"
  order_by     = "(name, timestamp)"
  partition_by = "toYYYYMM(timestamp)"
  columns = [
    { name = "name", type = "String" },
    { name = "timestamp", type = "DateTime64(3, 'UTC')", default_expression = "now()" },
    { name = "labels", type = "Map(String, String)" },
    { name = "increment", type = "Float64" },
  ]
}

module "custom_metrics_counters" {
  source = "../../lib/view"
  node   = var.node

  enabled    = contains(var.objects, "custom_metrics_counters")
  database   = var.database
  name       = "custom_metrics_counters"
  query      = "SELECT name, mapSort(labels) AS labels, sum(increment) AS value, '' AS help, 'counter' AS type FROM ${var.database}.custom_metrics_counter_events GROUP BY name, type, labels ORDER BY name ASC, type ASC, labels ASC"
  depends_on = [module.custom_metrics_counter_events]
}

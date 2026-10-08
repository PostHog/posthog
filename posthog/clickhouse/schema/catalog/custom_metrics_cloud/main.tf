# Production objects from before this catalogue, declared from their live definitions. Only Cloud roots
# in posthog-cloud-infra list them.

variable "node" {
  type    = any
  default = null
}

variable "database" {
  type    = string
  default = "posthog"
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



module "custom_metrics_events_recent_lag" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "custom_metrics_events_recent_lag")
  database = var.database
  name     = "custom_metrics_events_recent_lag"
  override = try(local.deployment.overrides["custom_metrics_events_recent_lag"], {})
  query    = <<-SQL
    SELECT 'ClickHouseCustomMetric_EventsRecentIngestionLag' AS name, map('instance', hostname()) AS labels, dateDiff('second', max(timestamp), now()) AS value, 'The number of seconds that have passed since the most recent event was inserted into events_recent table' AS help, 'gauge' AS type FROM ${var.database}.events_recent WHERE (team_id IN ['7964', '2323']) AND (event IN ('$heartbeat')) AND (timestamp < (now() + toIntervalMinute(3))) AND (inserted_at > (now() - toIntervalHour(3))) GROUP BY event
  SQL
}

module "custom_metrics_mutations" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "custom_metrics_mutations")
  database = var.database
  name     = "custom_metrics_mutations"
  override = try(local.deployment.overrides["custom_metrics_mutations"], {})
  query    = <<-SQL
    SELECT 'ClickHouseCustomMetric_OldestRunningMutationSeconds' AS name, map('instance', hostname(), 'database', database, 'table', `table`) AS labels, max(dateDiff('second', create_time, now())) AS value, 'Age in seconds of the oldest unfinished (is_done = 0) mutation for this database.table on this node' AS help, 'gauge' AS type FROM system.mutations WHERE is_done = 0 GROUP BY database, `table` HAVING value > 0
  SQL
}

module "custom_metrics_kafka_consumer_groups" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "custom_metrics_kafka_consumer_groups")
  database = var.database
  name     = "custom_metrics_kafka_consumer_groups"
  override = try(local.deployment.overrides["custom_metrics_kafka_consumer_groups"], {})
  query    = <<-SQL
    SELECT 'ClickHouseCustomMetric_KafkaConsumerGroupInfo' AS name, map('instance', hostname(), 'ch_cluster', (SELECT any(substitution) FROM system.macros WHERE macro = 'cluster'), 'kafka_cluster', kc, 'database', db, 'table', tbl, 'consumer_group', grp, 'topic', topic) AS labels, toUInt64(mvs) AS value, 'Kafka engine table on this node; value is the number of views attached to it (0 = nothing consumes it)' AS help, 'gauge' AS type FROM (SELECT database AS db, name AS tbl, extract(engine_full, 'kafka_group_name = '([^']+)'') AS grp, extract(engine_full, '^Kafka\('?([^,')]+)') AS kc, trimBoth(arrayJoin(splitByChar(',', extract(engine_full, 'kafka_topic_list = '([^']+)'')))) AS topic, length(dependencies_table) AS mvs FROM system.tables WHERE engine = 'Kafka') UNION ALL SELECT 'ClickHouseCustomMetric_KafkaConsumerAssignedPartitions' AS name, map('instance', hostname(), 'ch_cluster', (SELECT any(substitution) FROM system.macros WHERE macro = 'cluster'), 'kafka_cluster', t.kc, 'database', t.db, 'table', t.tbl, 'consumer_group', t.grp, 'topic', t.topic) AS labels, toUInt64(a.partitions) AS value, 'Kafka partitions this node holds for the table and topic' AS help, 'gauge' AS type FROM (SELECT database AS db, name AS tbl, extract(engine_full, 'kafka_group_name = '([^']+)'') AS grp, extract(engine_full, '^Kafka\('?([^,')]+)') AS kc, trimBoth(arrayJoin(splitByChar(',', extract(engine_full, 'kafka_topic_list = '([^']+)'')))) AS topic FROM system.tables WHERE engine = 'Kafka') AS t LEFT JOIN (SELECT database AS db, `table` AS tbl, arrayJoin(`assignments.topic`) AS topic, count() AS partitions FROM system.kafka_consumers GROUP BY db, tbl, topic) AS a ON (t.db = a.db) AND (t.tbl = a.tbl) AND (t.topic = a.topic) UNION ALL SELECT 'ClickHouseCustomMetric_KafkaConsumerSecondsSinceLastPoll' AS name, map('instance', hostname(), 'ch_cluster', (SELECT any(substitution) FROM system.macros WHERE macro = 'cluster'), 'kafka_cluster', t.kc, 'database', t.db, 'table', t.tbl, 'consumer_group', t.grp, 'topic', t.topic) AS labels, toUInt64(greatest(a.poll_age, 0)) AS value, 'Seconds since the oldest poll among consumers on this node that hold partitions for the table and topic' AS help, 'gauge' AS type FROM (SELECT database AS db, name AS tbl, extract(engine_full, 'kafka_group_name = '([^']+)'') AS grp, extract(engine_full, '^Kafka\('?([^,')]+)') AS kc, trimBoth(arrayJoin(splitByChar(',', extract(engine_full, 'kafka_topic_list = '([^']+)'')))) AS topic FROM system.tables WHERE engine = 'Kafka') AS t INNER JOIN (SELECT database AS db, `table` AS tbl, arrayJoin(`assignments.topic`) AS topic, max(dateDiff('second', last_poll_time, now())) AS poll_age FROM system.kafka_consumers GROUP BY db, tbl, topic) AS a ON (t.db = a.db) AND (t.tbl = a.tbl) AND (t.topic = a.topic) UNION ALL SELECT 'ClickHouseCustomMetric_KafkaConsumerExceptions15m' AS name, map('instance', hostname(), 'ch_cluster', (SELECT any(substitution) FROM system.macros WHERE macro = 'cluster'), 'kafka_cluster', t.kc, 'database', t.db, 'table', t.tbl, 'consumer_group', t.grp, 'topic', t.topic) AS labels, toUInt64(e.exceptions) AS value, 'Exceptions recorded by this node's consumers for the table in the last 15 minutes (capped by ClickHouse's per-consumer exception history)' AS help, 'gauge' AS type FROM (SELECT database AS db, name AS tbl, extract(engine_full, 'kafka_group_name = '([^']+)'') AS grp, extract(engine_full, '^Kafka\('?([^,')]+)') AS kc, trimBoth(arrayJoin(splitByChar(',', extract(engine_full, 'kafka_topic_list = '([^']+)'')))) AS topic FROM system.tables WHERE engine = 'Kafka') AS t LEFT JOIN (SELECT database AS db, `table` AS tbl, sum(arrayCount(x -> (x >= (now() - toIntervalMinute(15))), `exceptions.time`)) AS exceptions FROM system.kafka_consumers GROUP BY db, tbl) AS e ON (t.db = e.db) AND (t.tbl = e.tbl)
  SQL
}

module "custom_metrics_materialized_view_failures" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "custom_metrics_materialized_view_failures")
  database = var.database
  name     = "custom_metrics_materialized_view_failures"
  override = try(local.deployment.overrides["custom_metrics_materialized_view_failures"], {})
  query    = <<-SQL
    SELECT 'ClickHouseCustomMetric_MaterializedViewFailures5m' AS name, map('instance', hostname(), 'view_name', view_name, 'target_table', view_target, 'exception_code', toString(exception_code)) AS labels, count() AS value, 'Number of materialized view failures in the last 5 minutes' AS help, 'gauge' AS type FROM system.query_views_log WHERE (event_date >= yesterday()) AND (event_time >= (now() - toIntervalMinute(5))) AND (view_type = 'Materialized') AND (status IN ('ExceptionBeforeStart', 'ExceptionWhileProcessing')) GROUP BY view_name, view_target, exception_code
  SQL
}

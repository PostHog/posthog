# The aux log_entries Kafka consumer trio. Cloud placement is asymmetric (EU
# ingestion-small, US ingestion-medium) and cloud ingestion nodes are not in the
# managed set yet, so this layer is composed only on the local small node.
database "posthog" {
  table "writable_log_entries_aux" {
    column "team_id" { type = "UInt64" }
    column "log_source" { type = "LowCardinality(String)" }
    column "log_source_id" { type = "String" }
    column "instance_id" { type = "String" }
    column "timestamp" { type = "DateTime64(6, 'UTC')" }
    column "level" { type = "LowCardinality(String)" }
    column "message" { type = "String" }
    column "_timestamp" { type = "DateTime" }
    column "_offset" { type = "UInt64" }
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "log_entries_data"
    }
  }
  table "kafka_log_entries_aux" {
    column "team_id" { type = "UInt64" }
    column "log_source" { type = "LowCardinality(String)" }
    column "log_source_id" { type = "String" }
    column "instance_id" { type = "String" }
    column "timestamp" { type = "DateTime64(6, 'UTC')" }
    column "level" { type = "LowCardinality(String)" }
    column "message" { type = "String" }
    engine "kafka" {
      collection           = "warpstream_ingestion"
      topic_list           = "log_entries"
      group_name           = "clickhouse_log_entries_aux"
      format               = "JSONEachRow"
      skip_broken_messages = 100
      num_consumers        = 1
      thread_per_consumer  = true
      poll_timeout_ms      = 10000
      max_block_size       = 100000
    }
  }
  materialized_view "log_entries_aux_mv" {
    to_table = "posthog.writable_log_entries_aux"
    query    = file("sql/log_entries_aux_mv.sql")
    column "team_id" { type = "UInt64" }
    column "log_source" { type = "LowCardinality(String)" }
    column "log_source_id" { type = "String" }
    column "instance_id" { type = "String" }
    column "timestamp" { type = "DateTime64(6, 'UTC')" }
    column "level" { type = "LowCardinality(String)" }
    column "message" { type = "String" }
    column "_timestamp" { type = "DateTime" }
    column "_offset" { type = "UInt64" }
  }
}

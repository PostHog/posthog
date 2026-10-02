# log_entries on the aux cluster: the column core and
# the Distributed reader, composed by the aux and data nodes. The data table lives in
# roles/auxiliary/shared, the Kafka consumer trio in roles/coshared/log_entries_aux_write.
database "posthog" {
  table "_log_entries_aux_columns" {
    abstract = true
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
  table "log_entries_distributed" {
    extend = "_log_entries_aux_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "log_entries_data"
    }
  }
}

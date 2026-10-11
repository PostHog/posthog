# A second name for the aux log_entries reader on the aux nodes, so queries that name
# log_entries_distributed resolve there. Not composed on local-single, because the
# combined node carries the data-role log_entries_distributed (the main-cluster reader).
database "posthog" {
  table "log_entries_distributed" {
    extend = "_log_entries_aux_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "log_entries_data"
    }
  }
}

# Legacy-named alias of the aux log_entries reader, kept from the dual-write era
# so older references and pushed-down queries resolve on the aux cluster. Not
# composed on local-single, where the combined node carries the data-role naming.
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

# Shared: invariant custom_metrics_* sub-views (identical on every role). The custom_metrics aggregator is role-specific (see roles/ops).

database "posthog" {
  view "custom_metrics_backups" {
    query = file("sql/custom_metrics_backups.sql")
  }
  view "custom_metrics_dictionaries" {
    query = file("sql/custom_metrics_dictionaries.sql")
  }
  view "custom_metrics_part_counts" {
    query = file("sql/custom_metrics_part_counts.sql")
  }
  view "custom_metrics_replication_queue" {
    query = file("sql/custom_metrics_replication_queue.sql")
  }
  view "custom_metrics_server_crash" {
    query = file("sql/custom_metrics_server_crash.sql")
  }
  view "custom_metrics_table_sizes" {
    query = file("sql/custom_metrics_table_sizes.sql")
  }
  view "custom_metrics_test" {
    query = file("sql/custom_metrics_test.sql")
  }
}

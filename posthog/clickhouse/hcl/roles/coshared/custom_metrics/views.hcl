# The custom_metrics aggregator view, identical on the roles that host it (ops all
# envs + cloud logs). The invariant custom_metrics_* sub-views it reads live in
# roles/shared/custom_metrics.hcl; the local logs node does not run the aggregator.
database "posthog" {
  view "custom_metrics" {
    query = file("sql/custom_metrics.sql")
  }
}

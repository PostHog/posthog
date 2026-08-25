# The custom_metrics aggregator view, identical on the roles that host it: ops, and
# the cloud logs / ai_events / aux / batch_exports nodes. The invariant
# custom_metrics_* sub-views it reads live in roles/shared/custom_metrics.hcl; the
# local satellite nodes do not run the aggregator.
database "posthog" {
  view "custom_metrics" {
    query = file("sql/custom_metrics.sql")
  }
}

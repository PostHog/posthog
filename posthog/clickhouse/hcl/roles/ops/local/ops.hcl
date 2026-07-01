# OPS local-dev layer.
#
# Local dev composes the shared base layer as-is (query_log_archive data path +
# custom_metrics views). It has none of the cloud env extras (no prom_metrics,
# metrics suite, tophog, or events distributed proxies), so this layer adds
# nothing today — it exists as the explicit home for any future local-only
# override. Resolve local with: -layer .../ops/base,.../ops/env/local
database "posthog" {
}

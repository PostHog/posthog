# OPS prod-eu env layer — sharded_tophog (tophog zoo_path)
#
# query_log_archive_old (legacy/transitional) is intentionally unmanaged — not
# authored here and trimmed from the golden, so it is left untouched on the cluster.
#
# Generated/maintained as the declarative source of truth for the OPS ClickHouse cluster.
# Resolve with: hclexp load -layer <base>,<...>

database "posthog" {
}

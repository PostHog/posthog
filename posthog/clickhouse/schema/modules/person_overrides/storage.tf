# Tables that hold data, and the materialized views between them.

module "person_overrides" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "person_overrides")
  database     = var.database
  name         = "person_overrides"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.person_overrides${var.zk_path_suffix}', '{replica}-{shard}', version)"
  partition_by = "toYYYYMM(oldest_event)"
  order_by     = "(team_id, old_person_id)"
  columns = [
    { name = "team_id", type = "Int32" },
    { name = "old_person_id", type = "UUID" },
    { name = "override_person_id", type = "UUID" },
    { name = "merged_at", type = "DateTime64(6, 'UTC')" },
    { name = "oldest_event", type = "DateTime64(6, 'UTC')" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "version", type = "Int32" },
  ]
  override = try(var.overrides["person_overrides"], {})
}

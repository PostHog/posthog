module "person_overrides_family" {
  source = "../../lib/table_family"

  name     = "person_overrides"
  database = var.database
  layout   = "global"
  columns = [
    { name = "team_id", type = "Int32" },
    { name = "old_person_id", type = "UUID" },
    { name = "override_person_id", type = "UUID" },
    { name = "merged_at", type = "DateTime64(6, 'UTC')" },
    { name = "oldest_event", type = "DateTime64(6, 'UTC')" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "version", type = "Int32" },
  ]
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["version"]
    partition_by = "toYYYYMM(oldest_event)"
    order_by     = "(team_id, old_person_id)"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["person_overrides"], name) }
  })
}

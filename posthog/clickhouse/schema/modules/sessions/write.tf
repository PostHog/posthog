# Distributed tables that inserts go through.

module "writable_sessions" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_sessions")
  database = var.database
  name     = "writable_sessions"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_sessions', sipHash64(session_id))"
  columns  = local.sharded_sessions_columns
  override = try(var.overrides["writable_sessions"], {})
}

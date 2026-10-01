# Distributed tables that inserts go through.

module "writable_raw_sessions" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_raw_sessions")
  database = var.database
  name     = "writable_raw_sessions"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_raw_sessions', cityHash64(session_id_v7))"
  columns  = local.sharded_raw_sessions_columns
  override = try(var.overrides["writable_raw_sessions"], {})
}

module "writable_raw_sessions_v3" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_raw_sessions_v3")
  database = var.database
  name     = "writable_raw_sessions_v3"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_raw_sessions_v3', cityHash64(session_id_v7))"
  columns  = local.sharded_raw_sessions_v3_columns
  override = try(var.overrides["writable_raw_sessions_v3"], {})
}

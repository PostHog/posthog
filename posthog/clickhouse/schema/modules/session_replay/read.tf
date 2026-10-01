# Distributed tables, views and dictionaries that queries read from.

module "session_replay_embeddings" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "session_replay_embeddings")
  database = var.database
  name     = "session_replay_embeddings"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_session_replay_embeddings', sipHash64(session_id))"
  columns  = local.sharded_session_replay_embeddings_columns
  override = try(var.overrides["session_replay_embeddings"], {})
}

module "session_replay_events" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "session_replay_events")
  database = var.database
  name     = "session_replay_events"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_session_replay_events', sipHash64(distinct_id))"
  columns  = local.sharded_session_replay_events_columns
  override = try(var.overrides["session_replay_events"], {})
}

module "session_replay_features" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "session_replay_features")
  database = var.database
  name     = "session_replay_features"
  engine   = "Distributed('aux', '${var.database}', 'sharded_session_replay_features', sipHash64(session_id))"
  columns  = local.sharded_session_replay_features_columns
  override = try(var.overrides["session_replay_features"], {})
}

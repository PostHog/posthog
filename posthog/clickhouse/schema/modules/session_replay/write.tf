# Distributed tables that inserts go through.

module "writable_session_replay_embeddings" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_session_replay_embeddings")
  database = var.database
  name     = "writable_session_replay_embeddings"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_session_replay_embeddings', sipHash64(session_id))"
  columns  = local.sharded_session_replay_embeddings_columns
  override = try(var.overrides["writable_session_replay_embeddings"], {})
}

module "writable_session_replay_events" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_session_replay_events")
  database = var.database
  name     = "writable_session_replay_events"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_session_replay_events', sipHash64(distinct_id))"
  columns = [
    { name = "session_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "min_first_timestamp", type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))" },
    { name = "max_last_timestamp", type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))" },
    { name = "block_first_timestamps", type = "SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC')))" },
    { name = "block_last_timestamps", type = "SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC')))" },
    { name = "block_urls", type = "SimpleAggregateFunction(groupArrayArray, Array(String))" },
    { name = "first_url", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "all_urls", type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))" },
    { name = "click_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "keypress_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "mouse_activity_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "active_milliseconds", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "console_log_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "console_warn_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "console_error_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "size", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "message_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "event_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "snapshot_source", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "snapshot_library", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "snapshot_mode_v2", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "_timestamp", type = "SimpleAggregateFunction(max, DateTime)" },
    { name = "retention_period_days", type = "SimpleAggregateFunction(max, Nullable(Int64))" },
    { name = "is_deleted", type = "SimpleAggregateFunction(max, UInt8)", default_expression = "0" },
    { name = "ai_tags_fixed", type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))" },
    { name = "ai_tags_freeform", type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))" },
    { name = "ai_highlighted", type = "SimpleAggregateFunction(max, UInt8)", default_expression = "0" },
    { name = "surfacing_score", type = "SimpleAggregateFunction(max, Nullable(Float32))" },
  ]
  override = try(var.overrides["writable_session_replay_events"], {})
}

module "writable_session_replay_features" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_session_replay_features")
  database = var.database
  name     = "writable_session_replay_features"
  engine   = "Distributed('aux', '${var.database}', 'sharded_session_replay_features', sipHash64(session_id))"
  columns  = local.sharded_session_replay_features_columns
  override = try(var.overrides["writable_session_replay_features"], {})
}

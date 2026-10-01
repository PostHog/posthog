module "sharded_session_replay_embeddings_family" {
  source = "../../lib/table_family"

  name     = "session_replay_embeddings"
  database = var.database
  columns  = local.sharded_session_replay_embeddings_columns
  storage = {
    partition_by = "toYYYYMM(generation_timestamp)"
    order_by     = "(toDate(generation_timestamp), team_id, session_id)"
    ttl          = var.ttl ? "toDate(generation_timestamp) + toIntervalYear(1)" : null
    settings     = "index_granularity = 512"
  }
  sharding_key = "sipHash64(session_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.session_replay_embeddings"
    cluster     = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_session_replay_embeddings", "session_replay_embeddings", "writable_session_replay_embeddings"], name) }
  })
}

module "sharded_session_replay_events_family" {
  source = "../../lib/table_family"

  name     = "session_replay_events"
  database = var.database
  columns  = local.sharded_session_replay_events_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toYYYYMM(min_first_timestamp)"
    order_by     = "(toDate(min_first_timestamp), team_id, session_id)"
    settings     = "index_granularity = 512"
  }
  routing = {
    write_columns = [
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
  }
  sharding_key = "sipHash64(distinct_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.session_replay_events"
    cluster     = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_session_replay_events", "session_replay_events", "writable_session_replay_events"], name) }
  })
}

module "sharded_session_replay_features_family" {
  source = "../../lib/table_family"

  name     = "session_replay_features"
  database = var.database
  columns  = local.sharded_session_replay_features_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toYYYYMM(min_first_timestamp)"
    order_by     = "(team_id, session_id)"
    settings     = "index_granularity = 512"
  }
  sharding_key = "sipHash64(session_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.session_replay_features"
    cluster     = "aux"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_session_replay_features", "session_replay_features", "writable_session_replay_features"], name) }
  })
}

# Tables that hold data, and the materialized views between them.

module "sharded_session_replay_embeddings" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_session_replay_embeddings")
  database     = var.database
  name         = "sharded_session_replay_embeddings"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/{shard}/posthog.session_replay_embeddings${var.zk_path_suffix}', '{replica}')"
  partition_by = "toYYYYMM(generation_timestamp)"
  order_by     = "(toDate(generation_timestamp), team_id, session_id)"
  ttl          = var.ttl ? "toDate(generation_timestamp) + toIntervalYear(1)" : null
  settings     = "index_granularity = 512"
  columns      = local.sharded_session_replay_embeddings_columns
  override     = try(var.overrides["sharded_session_replay_embeddings"], {})
}

module "sharded_session_replay_events" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_session_replay_events")
  database     = var.database
  name         = "sharded_session_replay_events"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/{shard}/posthog.session_replay_events${var.zk_path_suffix}', '{replica}')"
  partition_by = "toYYYYMM(min_first_timestamp)"
  order_by     = "(toDate(min_first_timestamp), team_id, session_id)"
  settings     = "index_granularity = 512"
  columns      = local.sharded_session_replay_events_columns
  override     = try(var.overrides["sharded_session_replay_events"], {})
}

module "sharded_session_replay_features" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_session_replay_features")
  database     = var.database
  name         = "sharded_session_replay_features"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/{shard}/posthog.session_replay_features${var.zk_path_suffix}', '{replica}')"
  partition_by = "toYYYYMM(min_first_timestamp)"
  order_by     = "(team_id, session_id)"
  settings     = "index_granularity = 512"
  columns      = local.sharded_session_replay_features_columns
  override     = try(var.overrides["sharded_session_replay_features"], {})
}

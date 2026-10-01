module "sharded_events_recent_family" {
  source = "../../lib/table_family"

  name     = "distributed_events_recent"
  database = var.database
  columns  = local.sharded_events_recent_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["_timestamp"]
    partition_by = "toStartOfDay(inserted_at)"
    order_by     = "(team_id, toStartOfHour(inserted_at), event, cityHash64(distinct_id), cityHash64(uuid))"
    ttl          = var.ttl ? "toDate(inserted_at) + toIntervalDay(9)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    read_columns  = local.sharded_events_recent_columns
    write_columns = local.writable_events_recent_columns
  }
  sharding_key = "sipHash64(distinct_id)"
  deployment = merge({
    cluster      = "posthog_writable"
    read_cluster = "posthog_primary_replica"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_events_recent", "distributed_events_recent", "writable_events_recent"], name) }
  })
  names = { storage = "sharded_events_recent", write = "writable_events_recent" }
}

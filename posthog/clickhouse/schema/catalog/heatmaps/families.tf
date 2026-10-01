module "sharded_heatmaps_family" {
  source = "../../lib/table_family"

  name     = "heatmaps"
  database = var.database
  columns  = local.sharded_heatmaps_columns
  storage = {
    partition_by = "toYYYYMM(timestamp)"
    order_by     = "(type, team_id, toDate(timestamp), current_url, viewport_width)"
    ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(90)" : null
  }
  sharding_key = "cityHash64(concat(toString(team_id), '-', session_id, '-', toString(toDate(timestamp))))"
  kafka = {
    topic          = "clickhouse_heatmap_events"
    consumer_group = "group1"
    arguments      = "settings"
    columns        = local.kafka_heatmaps_columns
    settings       = {}
  }
  mv_select = <<-SQL
session_id,
    team_id,
    distinct_id,
    timestamp,
    x,
    y,
    scale_factor,
    viewport_width,
    viewport_height,
    pointer_target_fixed,
    current_url,
    type,
    _timestamp,
    _offset,
    _partition
  SQL
  deployment = merge({
    keeper_path      = "/clickhouse/tables/{shard}/${var.database}.heatmaps"
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_heatmaps", "heatmaps", "writable_heatmaps", "heatmaps_mv", "kafka_heatmaps"], name) }
  })
}

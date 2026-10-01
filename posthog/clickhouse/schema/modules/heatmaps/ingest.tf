# Kafka tables and the materialized views that consume them.

module "heatmaps_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "heatmaps_mv")
  database = var.database
  name     = "heatmaps_mv"
  to_table = "${var.database}.writable_heatmaps"
  query    = <<-SQL
    SELECT
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
    FROM ${var.database}.kafka_heatmaps
  SQL
  override = try(var.overrides["heatmaps_mv"], {})

  depends_on = [
    module.kafka_heatmaps,
    module.writable_heatmaps,
  ]
}

module "kafka_heatmaps" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_heatmaps")
  database = var.database
  name     = "kafka_heatmaps"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'clickhouse_heatmap_events'"
  columns  = local.kafka_heatmaps_columns
  override = try(var.overrides["kafka_heatmaps"], {})
}

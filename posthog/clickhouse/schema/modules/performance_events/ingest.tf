# Kafka tables and the materialized views that consume them.

module "kafka_performance_events" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_performance_events")
  database = var.database
  name     = "kafka_performance_events"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'clickhouse_performance_events'"
  columns  = local.kafka_performance_events_columns
  override = try(var.overrides["kafka_performance_events"], {})
}

module "performance_events_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "performance_events_mv")
  database = var.database
  name     = "performance_events_mv"
  to_table = "${var.database}.writeable_performance_events"
  query    = <<-SQL
    SELECT
        uuid,
        session_id,
        window_id,
        pageview_id,
        distinct_id,
        timestamp,
        time_origin,
        entry_type,
        name,
        team_id,
        current_url,
        start_time,
        duration,
        redirect_start,
        redirect_end,
        worker_start,
        fetch_start,
        domain_lookup_start,
        domain_lookup_end,
        connect_start,
        secure_connection_start,
        connect_end,
        request_start,
        response_start,
        response_end,
        decoded_body_size,
        encoded_body_size,
        initiator_type,
        next_hop_protocol,
        render_blocking_status,
        response_status,
        transfer_size,
        largest_contentful_paint_element,
        largest_contentful_paint_render_time,
        largest_contentful_paint_load_time,
        largest_contentful_paint_size,
        largest_contentful_paint_id,
        largest_contentful_paint_url,
        dom_complete,
        dom_content_loaded_event,
        dom_interactive,
        load_event_end,
        load_event_start,
        redirect_count,
        navigation_type,
        unload_event_end,
        unload_event_start,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_performance_events
  SQL
  override = try(var.overrides["performance_events_mv"], {})

  depends_on = [
    module.kafka_performance_events,
    module.writeable_performance_events,
  ]
}

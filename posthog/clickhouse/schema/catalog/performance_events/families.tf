module "sharded_performance_events_family" {
  source = "../../lib/table_family"

  name     = "performance_events"
  database = var.database
  columns  = local.sharded_performance_events_columns
  storage = {
    partition_by = "toYYYYMM(timestamp)"
    order_by     = "(team_id, toDate(timestamp), session_id, pageview_id, timestamp)"
    ttl          = var.ttl ? "toDate(timestamp) + toIntervalWeek(3)" : null
  }
  sharding_key = "sipHash64(session_id)"
  kafka = {
    topic          = "clickhouse_performance_events"
    consumer_group = "group1"
    arguments      = "settings"
    columns        = local.kafka_performance_events_columns
    settings       = {}
  }
  mv_select = <<-SQL
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
  SQL
  deployment = merge({
    keeper_path      = "/clickhouse/tables/{shard}/${var.database}.performance_events"
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_performance_events", "performance_events", "writeable_performance_events", "performance_events_mv", "kafka_performance_events"], name) }
  })
  names = { write = "writeable_performance_events" }
}

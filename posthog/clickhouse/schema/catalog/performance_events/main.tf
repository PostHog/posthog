variable "node" {
  description = "The server these objects live on: { name, host, port, leader }. Null puts them on the provider's host."
  type        = any
  default     = null
}

variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "ttl" {
  description = "Set table TTLs. Tests turn them off, because they insert rows with old timestamps."
  type        = bool
  default     = true
}

variable "objects" {
  description = "Names of the objects to create."
  type        = set(string)
}

variable "test" {
  description = "Use the definitions the test suite expects."
  type        = bool
  default     = false
}

variable "deployment" { type = any }

locals {
  deployment = merge({ overrides = {} }, var.deployment)
}

# Column lists that more than one object uses.

locals {
  kafka_performance_events_columns = [
    { name = "uuid", type = "UUID" },
    { name = "session_id", type = "String" },
    { name = "window_id", type = "String" },
    { name = "pageview_id", type = "String" },
    { name = "distinct_id", type = "String" },
    { name = "timestamp", type = "DateTime64(3)" },
    { name = "time_origin", type = "DateTime64(3, 'UTC')" },
    { name = "entry_type", type = "LowCardinality(String)" },
    { name = "name", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "current_url", type = "String" },
    { name = "start_time", type = "Float64" },
    { name = "duration", type = "Float64" },
    { name = "redirect_start", type = "Float64" },
    { name = "redirect_end", type = "Float64" },
    { name = "worker_start", type = "Float64" },
    { name = "fetch_start", type = "Float64" },
    { name = "domain_lookup_start", type = "Float64" },
    { name = "domain_lookup_end", type = "Float64" },
    { name = "connect_start", type = "Float64" },
    { name = "secure_connection_start", type = "Float64" },
    { name = "connect_end", type = "Float64" },
    { name = "request_start", type = "Float64" },
    { name = "response_start", type = "Float64" },
    { name = "response_end", type = "Float64" },
    { name = "decoded_body_size", type = "Int64" },
    { name = "encoded_body_size", type = "Int64" },
    { name = "initiator_type", type = "LowCardinality(String)" },
    { name = "next_hop_protocol", type = "LowCardinality(String)" },
    { name = "render_blocking_status", type = "LowCardinality(String)" },
    { name = "response_status", type = "Int64" },
    { name = "transfer_size", type = "Int64" },
    { name = "largest_contentful_paint_element", type = "String" },
    { name = "largest_contentful_paint_render_time", type = "Float64" },
    { name = "largest_contentful_paint_load_time", type = "Float64" },
    { name = "largest_contentful_paint_size", type = "Float64" },
    { name = "largest_contentful_paint_id", type = "String" },
    { name = "largest_contentful_paint_url", type = "String" },
    { name = "dom_complete", type = "Float64" },
    { name = "dom_content_loaded_event", type = "Float64" },
    { name = "dom_interactive", type = "Float64" },
    { name = "load_event_end", type = "Float64" },
    { name = "load_event_start", type = "Float64" },
    { name = "redirect_count", type = "Int64" },
    { name = "navigation_type", type = "LowCardinality(String)" },
    { name = "unload_event_end", type = "Float64" },
    { name = "unload_event_start", type = "Float64" },
  ]

  sharded_performance_events_columns = concat(local.kafka_performance_events_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])
}

module "sharded_performance_events_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

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
  }, local.deployment)
  names = { write = "writeable_performance_events" }
}

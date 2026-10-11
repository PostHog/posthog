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

locals {
}

# Column lists that more than one object uses.

locals {
  sharded_session_replay_embeddings_columns = [
    { name = "session_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "embeddings", type = "Array(Float32)" },
    { name = "generation_timestamp", type = "DateTime64(6, 'UTC')", default_expression = "now('UTC')" },
    { name = "source_type", type = "LowCardinality(String)" },
    { name = "input", type = "String" },
  ]

  sharded_session_replay_events_columns = [
    { name = "session_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "min_first_timestamp", type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))" },
    { name = "max_last_timestamp", type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))" },
    { name = "first_url", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
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
    { name = "_timestamp", type = "SimpleAggregateFunction(max, DateTime)" },
    { name = "snapshot_source", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "all_urls", type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))" },
    { name = "snapshot_library", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "block_first_timestamps", type = "SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC')))" },
    { name = "block_last_timestamps", type = "SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC')))" },
    { name = "block_urls", type = "SimpleAggregateFunction(groupArrayArray, Array(String))" },
    { name = "retention_period_days", type = "SimpleAggregateFunction(max, Nullable(Int64))" },
    { name = "is_deleted", type = "SimpleAggregateFunction(max, UInt8)", default_expression = "0" },
    { name = "ai_tags_fixed", type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))" },
    { name = "ai_tags_freeform", type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))" },
    { name = "ai_highlighted", type = "SimpleAggregateFunction(max, UInt8)", default_expression = "0" },
    { name = "surfacing_score", type = "SimpleAggregateFunction(max, Nullable(Float32))" },
    { name = "snapshot_mode_v2", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
  ]

  sharded_session_replay_features_columns = [
    { name = "session_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "min_first_timestamp", type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))" },
    { name = "max_last_timestamp", type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))" },
    { name = "event_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "mouse_position_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "mouse_sum_x", type = "SimpleAggregateFunction(sum, Float64)" },
    { name = "mouse_sum_x_squared", type = "SimpleAggregateFunction(sum, Float64)" },
    { name = "mouse_sum_y", type = "SimpleAggregateFunction(sum, Float64)" },
    { name = "mouse_sum_y_squared", type = "SimpleAggregateFunction(sum, Float64)" },
    { name = "mouse_distance_traveled", type = "SimpleAggregateFunction(sum, Float64)" },
    { name = "mouse_direction_change_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "mouse_velocity_sum", type = "SimpleAggregateFunction(sum, Float64)" },
    { name = "mouse_velocity_sum_of_squares", type = "SimpleAggregateFunction(sum, Float64)" },
    { name = "mouse_velocity_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "scroll_event_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "total_scroll_magnitude", type = "SimpleAggregateFunction(sum, Float64)" },
    { name = "scroll_direction_reversal_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "rapid_scroll_reversal_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "scroll_to_top_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "click_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "keypress_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "mouse_activity_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "rage_click_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "dead_click_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "backspace_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "inter_action_gap_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "inter_action_gap_sum_ms", type = "SimpleAggregateFunction(sum, Float64)" },
    { name = "inter_action_gap_sum_of_squares_ms", type = "SimpleAggregateFunction(sum, Float64)" },
    { name = "max_idle_gap_ms", type = "SimpleAggregateFunction(max, Float64)" },
    { name = "long_idle_gap_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "quick_back_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "page_visit_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "unique_url_count", type = "AggregateFunction(uniqCombined(12), String)" },
    { name = "login_path_visit_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "signup_path_visit_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "checkout_path_visit_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "cart_path_visit_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "billing_path_visit_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "settings_path_visit_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "account_path_visit_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "error_path_visit_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "not_found_path_visit_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "admin_path_visit_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "dashboard_path_visit_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "onboarding_path_visit_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "cancel_path_visit_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "refund_path_visit_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "console_error_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "console_error_after_click_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "console_warn_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "network_request_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "network_failed_request_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "network_4xx_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "network_5xx_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "network_request_duration_sum", type = "SimpleAggregateFunction(sum, Float64)" },
    { name = "network_request_duration_sum_of_squares", type = "SimpleAggregateFunction(sum, Float64)" },
    { name = "network_request_duration_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "mutation_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "viewport_resize_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "touch_event_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "max_scroll_y", type = "SimpleAggregateFunction(max, Float64)" },
    { name = "unique_click_target_count", type = "AggregateFunction(uniqCombined(12), Int64)" },
    { name = "unique_form_field_count", type = "AggregateFunction(uniqCombined(12), Int64)" },
    { name = "text_selection_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "selection_copy_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "is_deleted", type = "SimpleAggregateFunction(max, UInt8)", default_expression = "0" },
  ]
}

module "sharded_session_replay_embeddings_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

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
  }, local.deployment)
}

module "sharded_session_replay_events_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

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
  }, local.deployment)
}

module "sharded_session_replay_features_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

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
  }, local.deployment)
}

# Kafka tables and the materialized views that consume them.

module "kafka_session_replay_events" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_session_replay_events")
  database = var.database
  name     = "kafka_session_replay_events"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'clickhouse_session_replay_events'"
  columns = [
    { name = "session_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "first_timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "last_timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "block_url", type = "Nullable(String)" },
    { name = "first_url", type = "Nullable(String)" },
    { name = "urls", type = "Array(String)" },
    { name = "click_count", type = "Int64" },
    { name = "keypress_count", type = "Int64" },
    { name = "mouse_activity_count", type = "Int64" },
    { name = "active_milliseconds", type = "Int64" },
    { name = "console_log_count", type = "Int64" },
    { name = "console_warn_count", type = "Int64" },
    { name = "console_error_count", type = "Int64" },
    { name = "size", type = "Int64" },
    { name = "event_count", type = "Int64" },
    { name = "message_count", type = "Int64" },
    { name = "snapshot_source", type = "LowCardinality(Nullable(String))" },
    { name = "snapshot_library", type = "Nullable(String)" },
    { name = "snapshot_mode", type = "LowCardinality(Nullable(String))" },
    { name = "retention_period_days", type = "Nullable(Int64)" },
    { name = "is_deleted", type = "UInt8" },
    { name = "ai_tags_fixed", type = "Array(String)" },
    { name = "ai_tags_freeform", type = "Array(String)" },
    { name = "ai_highlighted", type = "UInt8" },
    { name = "surfacing_score", type = "Nullable(Float32)" },
  ]
  override = try(local.deployment.overrides["kafka_session_replay_events"], {})
}

module "kafka_session_replay_features" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_session_replay_features")
  database = var.database
  name     = "kafka_session_replay_features"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'clickhouse_session_replay_features'"
  columns = [
    { name = "session_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "batch_id", type = "String" },
    { name = "first_timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "last_timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "event_count", type = "Int64" },
    { name = "mouse_position_count", type = "Int64" },
    { name = "mouse_sum_x", type = "Float64" },
    { name = "mouse_sum_x_squared", type = "Float64" },
    { name = "mouse_sum_y", type = "Float64" },
    { name = "mouse_sum_y_squared", type = "Float64" },
    { name = "mouse_distance_traveled", type = "Float64" },
    { name = "mouse_direction_change_count", type = "Int64" },
    { name = "mouse_velocity_sum", type = "Float64" },
    { name = "mouse_velocity_sum_of_squares", type = "Float64" },
    { name = "mouse_velocity_count", type = "Int64" },
    { name = "scroll_event_count", type = "Int64" },
    { name = "total_scroll_magnitude", type = "Float64" },
    { name = "scroll_direction_reversal_count", type = "Int64" },
    { name = "rapid_scroll_reversal_count", type = "Int64" },
    { name = "scroll_to_top_count", type = "Int64" },
    { name = "click_count", type = "Int64" },
    { name = "keypress_count", type = "Int64" },
    { name = "mouse_activity_count", type = "Int64" },
    { name = "rage_click_count", type = "Int64" },
    { name = "dead_click_count", type = "Int64" },
    { name = "backspace_count", type = "Int64" },
    { name = "inter_action_gap_count", type = "Int64" },
    { name = "inter_action_gap_sum_ms", type = "Float64" },
    { name = "inter_action_gap_sum_of_squares_ms", type = "Float64" },
    { name = "max_idle_gap_ms", type = "Float64" },
    { name = "long_idle_gap_count", type = "Int64" },
    { name = "quick_back_count", type = "Int64" },
    { name = "page_visit_count", type = "Int64" },
    { name = "visited_urls", type = "Array(String)" },
    { name = "login_path_visit_count", type = "Int64" },
    { name = "signup_path_visit_count", type = "Int64" },
    { name = "checkout_path_visit_count", type = "Int64" },
    { name = "cart_path_visit_count", type = "Int64" },
    { name = "billing_path_visit_count", type = "Int64" },
    { name = "settings_path_visit_count", type = "Int64" },
    { name = "account_path_visit_count", type = "Int64" },
    { name = "error_path_visit_count", type = "Int64" },
    { name = "not_found_path_visit_count", type = "Int64" },
    { name = "admin_path_visit_count", type = "Int64" },
    { name = "dashboard_path_visit_count", type = "Int64" },
    { name = "onboarding_path_visit_count", type = "Int64" },
    { name = "cancel_path_visit_count", type = "Int64" },
    { name = "refund_path_visit_count", type = "Int64" },
    { name = "console_error_count", type = "Int64" },
    { name = "console_error_after_click_count", type = "Int64" },
    { name = "console_warn_count", type = "Int64" },
    { name = "network_request_count", type = "Int64" },
    { name = "network_failed_request_count", type = "Int64" },
    { name = "network_4xx_count", type = "Int64" },
    { name = "network_5xx_count", type = "Int64" },
    { name = "network_request_duration_sum", type = "Float64" },
    { name = "network_request_duration_sum_of_squares", type = "Float64" },
    { name = "network_request_duration_count", type = "Int64" },
    { name = "mutation_count", type = "Int64" },
    { name = "viewport_resize_count", type = "Int64" },
    { name = "touch_event_count", type = "Int64" },
    { name = "max_scroll_y", type = "Float64" },
    { name = "click_target_ids", type = "Array(Int64)" },
    { name = "form_field_ids", type = "Array(Int64)" },
    { name = "text_selection_count", type = "Int64" },
    { name = "selection_copy_count", type = "Int64" },
    { name = "is_deleted", type = "UInt8" },
  ]
  override = try(local.deployment.overrides["kafka_session_replay_features"], {})
}

module "session_replay_events_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "session_replay_events_mv")
  database = var.database
  name     = "session_replay_events_mv"
  to_table = "${var.database}.writable_session_replay_events"
  query    = <<-SQL
    SELECT
        session_id,
        team_id,
        any(distinct_id) AS distinct_id,
        min(first_timestamp) AS min_first_timestamp,
        max(last_timestamp) AS max_last_timestamp,
        groupArray(if(block_url != '', first_timestamp, NULL)) AS block_first_timestamps,
        groupArray(if(block_url != '', last_timestamp, NULL)) AS block_last_timestamps,
        groupArray(block_url) AS block_urls,
        argMinState(first_url, first_timestamp) AS first_url,
        groupUniqArrayArray(urls) AS all_urls,
        sum(click_count) AS click_count,
        sum(keypress_count) AS keypress_count,
        sum(mouse_activity_count) AS mouse_activity_count,
        sum(active_milliseconds) AS active_milliseconds,
        sum(console_log_count) AS console_log_count,
        sum(console_warn_count) AS console_warn_count,
        sum(console_error_count) AS console_error_count,
        sum(size) AS size,
        sum(message_count) AS message_count,
        sum(event_count) AS event_count,
        argMinState(replay.snapshot_source, first_timestamp) AS snapshot_source,
        argMinState(snapshot_library, first_timestamp) AS snapshot_library,
        max(_timestamp) AS _timestamp,
        max(retention_period_days) AS retention_period_days,
        max(is_deleted) AS is_deleted,
        groupUniqArrayArray(ai_tags_fixed) AS ai_tags_fixed,
        groupUniqArrayArray(ai_tags_freeform) AS ai_tags_freeform,
        max(ai_highlighted) AS ai_highlighted,
        max(surfacing_score) AS surfacing_score,
        argMinState(replay.snapshot_mode, first_timestamp) AS snapshot_mode_v2
    FROM ${var.database}.kafka_session_replay_events AS replay
    GROUP BY
        session_id,
        team_id
  SQL
  override = try(local.deployment.overrides["session_replay_events_mv"], {})

  depends_on = [
    module.kafka_session_replay_events,
    module.sharded_session_replay_events_family,
  ]
}

module "session_replay_features_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "session_replay_features_mv")
  database = var.database
  name     = "session_replay_features_mv"
  to_table = "${var.database}.writable_session_replay_features"
  query    = <<-SQL
    SELECT
        session_id,
        team_id,
        any(distinct_id) AS distinct_id,
        min(first_timestamp) AS min_first_timestamp,
        max(last_timestamp) AS max_last_timestamp,
        sum(event_count) AS event_count,
        sum(mouse_position_count) AS mouse_position_count,
        sum(mouse_sum_x) AS mouse_sum_x,
        sum(mouse_sum_x_squared) AS mouse_sum_x_squared,
        sum(mouse_sum_y) AS mouse_sum_y,
        sum(mouse_sum_y_squared) AS mouse_sum_y_squared,
        sum(mouse_distance_traveled) AS mouse_distance_traveled,
        sum(mouse_direction_change_count) AS mouse_direction_change_count,
        sum(mouse_velocity_sum) AS mouse_velocity_sum,
        sum(mouse_velocity_sum_of_squares) AS mouse_velocity_sum_of_squares,
        sum(mouse_velocity_count) AS mouse_velocity_count,
        sum(scroll_event_count) AS scroll_event_count,
        sum(total_scroll_magnitude) AS total_scroll_magnitude,
        sum(scroll_direction_reversal_count) AS scroll_direction_reversal_count,
        sum(rapid_scroll_reversal_count) AS rapid_scroll_reversal_count,
        sum(scroll_to_top_count) AS scroll_to_top_count,
        sum(click_count) AS click_count,
        sum(keypress_count) AS keypress_count,
        sum(mouse_activity_count) AS mouse_activity_count,
        sum(rage_click_count) AS rage_click_count,
        sum(dead_click_count) AS dead_click_count,
        sum(backspace_count) AS backspace_count,
        sum(inter_action_gap_count) AS inter_action_gap_count,
        sum(inter_action_gap_sum_ms) AS inter_action_gap_sum_ms,
        sum(inter_action_gap_sum_of_squares_ms) AS inter_action_gap_sum_of_squares_ms,
        max(max_idle_gap_ms) AS max_idle_gap_ms,
        sum(long_idle_gap_count) AS long_idle_gap_count,
        sum(quick_back_count) AS quick_back_count,
        sum(page_visit_count) AS page_visit_count,
        uniqCombinedArrayState(12)(visited_urls) AS unique_url_count,
        sum(login_path_visit_count) AS login_path_visit_count,
        sum(signup_path_visit_count) AS signup_path_visit_count,
        sum(checkout_path_visit_count) AS checkout_path_visit_count,
        sum(cart_path_visit_count) AS cart_path_visit_count,
        sum(billing_path_visit_count) AS billing_path_visit_count,
        sum(settings_path_visit_count) AS settings_path_visit_count,
        sum(account_path_visit_count) AS account_path_visit_count,
        sum(error_path_visit_count) AS error_path_visit_count,
        sum(not_found_path_visit_count) AS not_found_path_visit_count,
        sum(admin_path_visit_count) AS admin_path_visit_count,
        sum(dashboard_path_visit_count) AS dashboard_path_visit_count,
        sum(onboarding_path_visit_count) AS onboarding_path_visit_count,
        sum(cancel_path_visit_count) AS cancel_path_visit_count,
        sum(refund_path_visit_count) AS refund_path_visit_count,
        sum(console_error_count) AS console_error_count,
        sum(console_error_after_click_count) AS console_error_after_click_count,
        sum(console_warn_count) AS console_warn_count,
        sum(network_request_count) AS network_request_count,
        sum(network_failed_request_count) AS network_failed_request_count,
        sum(network_4xx_count) AS network_4xx_count,
        sum(network_5xx_count) AS network_5xx_count,
        sum(network_request_duration_sum) AS network_request_duration_sum,
        sum(network_request_duration_sum_of_squares) AS network_request_duration_sum_of_squares,
        sum(network_request_duration_count) AS network_request_duration_count,
        sum(mutation_count) AS mutation_count,
        sum(viewport_resize_count) AS viewport_resize_count,
        sum(touch_event_count) AS touch_event_count,
        max(max_scroll_y) AS max_scroll_y,
        uniqCombinedArrayState(12)(click_target_ids) AS unique_click_target_count,
        uniqCombinedArrayState(12)(form_field_ids) AS unique_form_field_count,
        sum(text_selection_count) AS text_selection_count,
        sum(selection_copy_count) AS selection_copy_count,
        max(is_deleted) AS is_deleted
    FROM ${var.database}.kafka_session_replay_features
    GROUP BY
        session_id,
        team_id
  SQL
  override = try(local.deployment.overrides["session_replay_features_mv"], {})

  depends_on = [
    module.kafka_session_replay_features,
    module.sharded_session_replay_features_family,
  ]
}

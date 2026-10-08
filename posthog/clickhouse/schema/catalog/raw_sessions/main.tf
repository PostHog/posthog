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

# Reads from events, session_replay. Those must exist on the node first.

locals {
  test = var.test
}

# Column lists that more than one object uses.

locals {
  sharded_raw_sessions_v3_columns = [
    { name = "team_id", type = "Int64" },
    { name = "session_id_v7", type = "UInt128" },
    { name = "session_timestamp", type = "DateTime64(3)", default_expression = "fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80)))" },
    { name = "distinct_id", type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))" },
    { name = "distinct_ids", type = "AggregateFunction(groupUniqArray, String)" },
    { name = "min_timestamp", type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))" },
    { name = "max_timestamp", type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))" },
    { name = "max_inserted_at", type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))" },
    { name = "urls", type = "SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String))" },
    { name = "entry_url", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "end_url", type = "AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "last_external_click_url", type = "AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "browser", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "browser_version", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "os", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "os_version", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "device_type", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "viewport_width", type = "AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC'))" },
    { name = "viewport_height", type = "AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC'))" },
    { name = "geoip_country_code", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "geoip_subdivision_1_code", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "geoip_subdivision_1_name", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "geoip_subdivision_city_name", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "geoip_time_zone", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "entry_referring_domain", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "entry_utm_source", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "entry_utm_campaign", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "entry_utm_medium", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "entry_utm_term", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "entry_utm_content", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "entry_gclid", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "entry_gad_source", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "entry_fbclid", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
    { name = "entry_has_gclid", type = "AggregateFunction(argMin, Bool, DateTime64(6, 'UTC'))" },
    { name = "entry_has_fbclid", type = "AggregateFunction(argMin, Bool, DateTime64(6, 'UTC'))" },
    { name = "entry_ad_ids_map", type = "AggregateFunction(argMin, Map(String, String), DateTime64(6, 'UTC'))" },
    { name = "entry_ad_ids_set", type = "AggregateFunction(argMin, Array(String), DateTime64(6, 'UTC'))" },
    { name = "entry_channel_type_properties", type = "AggregateFunction(argMin, Tuple(Nullable(String), Nullable(String), Nullable(String), Nullable(String), Bool, Bool, Nullable(String)), DateTime64(6, 'UTC'))" },
    { name = "pageview_uniq", type = "AggregateFunction(uniqExact, Nullable(UUID))" },
    { name = "autocapture_uniq", type = "AggregateFunction(uniqExact, Nullable(UUID))" },
    { name = "screen_uniq", type = "AggregateFunction(uniqExact, Nullable(UUID))" },
    { name = "page_screen_uniq_up_to", type = "AggregateFunction(uniqUpTo(1), Nullable(UUID))" },
    { name = "has_autocapture", type = "SimpleAggregateFunction(max, Bool)" },
    { name = "flag_key_values", type = "SimpleAggregateFunction(groupUniqArrayArray(10000), Array(String))" },
    { name = "flag_keys", type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))" },
    { name = "event_names", type = "SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String))" },
    { name = "hosts", type = "SimpleAggregateFunction(groupUniqArrayArray(100), Array(String))" },
    { name = "emails", type = "SimpleAggregateFunction(groupUniqArrayArray(10), Array(String))" },
    { name = "has_replay_events", type = "SimpleAggregateFunction(max, Bool)" },
  ]

  sharded_raw_sessions_columns = [
    { name = "team_id", type = "Int64" },
    { name = "session_id_v7", type = "UInt128" },
    { name = "distinct_id", type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))" },
    { name = "min_timestamp", type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))" },
    { name = "max_timestamp", type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))" },
    { name = "max_inserted_at", type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))" },
    { name = "urls", type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))" },
    { name = "entry_url", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "end_url", type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))" },
    { name = "last_external_click_url", type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))" },
    { name = "initial_browser", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_browser_version", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_os", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_os_version", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_device_type", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_viewport_width", type = "AggregateFunction(argMin, Int64, DateTime64(6, 'UTC'))" },
    { name = "initial_viewport_height", type = "AggregateFunction(argMin, Int64, DateTime64(6, 'UTC'))" },
    { name = "initial_geoip_country_code", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_geoip_subdivision_1_code", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_geoip_subdivision_1_name", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_geoip_subdivision_city_name", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_geoip_time_zone", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_referring_domain", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_utm_source", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_utm_campaign", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_utm_medium", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_utm_term", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_utm_content", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_gclid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_gad_source", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_gclsrc", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_dclid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_gbraid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_wbraid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_fbclid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_msclkid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_twclid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_li_fat_id", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_mc_cid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_igshid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_ttclid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_epik", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_qclid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_sccid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial__kx", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_irclid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "pageview_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "pageview_uniq", type = "AggregateFunction(uniq, Nullable(UUID))" },
    { name = "autocapture_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "autocapture_uniq", type = "AggregateFunction(uniq, Nullable(UUID))" },
    { name = "screen_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "screen_uniq", type = "AggregateFunction(uniq, Nullable(UUID))" },
    { name = "maybe_has_session_replay", type = "SimpleAggregateFunction(max, Bool)" },
    { name = "page_screen_autocapture_uniq_up_to", type = "AggregateFunction(uniqUpTo(1), Nullable(UUID))" },
    { name = "vitals_lcp", type = "AggregateFunction(argMin, Nullable(Float64), DateTime64(6, 'UTC'))" },
  ]
}

module "sharded_raw_sessions_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "raw_sessions"
  database = var.database
  columns  = local.sharded_raw_sessions_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toYYYYMM(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000)))"
    order_by     = "(team_id, toStartOfHour(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000))), cityHash64(session_id_v7), session_id_v7)"
    sample_by    = "cityHash64(session_id_v7)"
  }
  sharding_key = "cityHash64(session_id_v7)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.raw_sessions"
    cluster     = "posthog"
  }, local.deployment)
}

module "sharded_raw_sessions_v3_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "raw_sessions_v3"
  database = var.database
  columns  = local.sharded_raw_sessions_v3_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toYYYYMM(session_timestamp)"
    order_by     = "(team_id, session_timestamp, session_id_v7)"
    settings     = "index_granularity = 8192, max_delay_to_insert = 10, parts_to_delay_insert = 250, parts_to_throw_insert = 1000"
    indexes = [
      { name = "event_names_bloom_filter", expression = "event_names", type = "bloom_filter()", granularity = 1 },
      { name = "flag_key_values_bloom_filter", expression = "flag_key_values", type = "bloom_filter()", granularity = 1 },
      { name = "flag_keys_bloom_filter", expression = "flag_keys", type = "bloom_filter()", granularity = 1 },
      { name = "hosts_bloom_filter", expression = "hosts", type = "bloom_filter()", granularity = 1 },
      { name = "emails_bloom_filter", expression = "emails", type = "bloom_filter()", granularity = 1 },
    ]
  }
  routing = {
    read_columns = [
      { name = "team_id", type = "Int64" },
      { name = "session_id_v7", type = "UInt128" },
      { name = "session_timestamp", type = "DateTime64(3)", materialized_expression = "fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80)))" },
      { name = "distinct_id", type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))" },
      { name = "distinct_ids", type = "AggregateFunction(groupUniqArray, String)" },
      { name = "min_timestamp", type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))" },
      { name = "max_timestamp", type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))" },
      { name = "max_inserted_at", type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))" },
      { name = "urls", type = "SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String))" },
      { name = "entry_url", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "end_url", type = "AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "last_external_click_url", type = "AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "browser", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "browser_version", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "os", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "os_version", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "device_type", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "viewport_width", type = "AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC'))" },
      { name = "viewport_height", type = "AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC'))" },
      { name = "geoip_country_code", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "geoip_subdivision_1_code", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "geoip_subdivision_1_name", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "geoip_subdivision_city_name", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "geoip_time_zone", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "entry_referring_domain", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "entry_utm_source", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "entry_utm_campaign", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "entry_utm_medium", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "entry_utm_term", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "entry_utm_content", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "entry_gclid", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "entry_gad_source", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "entry_fbclid", type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))" },
      { name = "entry_has_gclid", type = "AggregateFunction(argMin, Bool, DateTime64(6, 'UTC'))" },
      { name = "entry_has_fbclid", type = "AggregateFunction(argMin, Bool, DateTime64(6, 'UTC'))" },
      { name = "entry_ad_ids_map", type = "AggregateFunction(argMin, Map(String, String), DateTime64(6, 'UTC'))" },
      { name = "entry_ad_ids_set", type = "AggregateFunction(argMin, Array(String), DateTime64(6, 'UTC'))" },
      { name = "entry_channel_type_properties", type = "AggregateFunction(argMin, Tuple(Nullable(String), Nullable(String), Nullable(String), Nullable(String), Bool, Bool, Nullable(String)), DateTime64(6, 'UTC'))" },
      { name = "pageview_uniq", type = "AggregateFunction(uniqExact, Nullable(UUID))" },
      { name = "autocapture_uniq", type = "AggregateFunction(uniqExact, Nullable(UUID))" },
      { name = "screen_uniq", type = "AggregateFunction(uniqExact, Nullable(UUID))" },
      { name = "page_screen_uniq_up_to", type = "AggregateFunction(uniqUpTo(1), Nullable(UUID))" },
      { name = "has_autocapture", type = "SimpleAggregateFunction(max, Bool)" },
      { name = "flag_key_values", type = "SimpleAggregateFunction(groupUniqArrayArray(10000), Array(String))" },
      { name = "flag_keys", type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))" },
      { name = "event_names", type = "SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String))" },
      { name = "hosts", type = "SimpleAggregateFunction(groupUniqArrayArray(100), Array(String))" },
      { name = "emails", type = "SimpleAggregateFunction(groupUniqArrayArray(10), Array(String))" },
      { name = "has_replay_events", type = "SimpleAggregateFunction(max, Bool)" },
    ]
  }
  sharding_key = "cityHash64(session_id_v7)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.raw_sessions_v3"
    cluster     = "posthog"
  }, local.deployment)
}

# Tables that hold data, and the materialized views between them.

module "raw_sessions_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "raw_sessions_mv")
  database = var.database
  name     = "raw_sessions_mv"
  to_table = "${var.database}.writable_raw_sessions"
  query    = <<-SQL
    SELECT
        team_id,
        toUInt128(toUUID(`$session_id`)) AS session_id_v7,
        argMaxState(distinct_id, timestamp) AS distinct_id,
        min(timestamp) AS min_timestamp,
        max(timestamp) AS max_timestamp,
        max(coalesce(inserted_at, now64())) AS max_inserted_at,
        groupUniqArray(nullIf(JSONExtractString(properties, '$current_url'), '')) AS urls,
        argMinState(JSONExtractString(properties, '$current_url'), timestamp) AS entry_url,
        argMaxState(JSONExtractString(properties, '$current_url'), timestamp) AS end_url,
        argMaxState(JSONExtractString(properties, '$external_click_url'), timestamp) AS last_external_click_url,
        argMinState(JSONExtractString(properties, '$browser'), timestamp) AS initial_browser,
        argMinState(JSONExtractString(properties, '$browser_version'), timestamp) AS initial_browser_version,
        argMinState(JSONExtractString(properties, '$os'), timestamp) AS initial_os,
        argMinState(JSONExtractString(properties, '$os_version'), timestamp) AS initial_os_version,
        argMinState(JSONExtractString(properties, '$device_type'), timestamp) AS initial_device_type,
        argMinState(JSONExtractInt(properties, '$viewport_width'), timestamp) AS initial_viewport_width,
        argMinState(JSONExtractInt(properties, '$viewport_height'), timestamp) AS initial_viewport_height,
        argMinState(JSONExtractString(properties, '$geoip_country_code'), timestamp) AS initial_geoip_country_code,
        argMinState(JSONExtractString(properties, '$geoip_subdivision_1_code'), timestamp) AS initial_geoip_subdivision_1_code,
        argMinState(JSONExtractString(properties, '$geoip_subdivision_1_name'), timestamp) AS initial_geoip_subdivision_1_name,
        argMinState(JSONExtractString(properties, '$geoip_subdivision_city_name'), timestamp) AS initial_geoip_subdivision_city_name,
        argMinState(JSONExtractString(properties, '$geoip_time_zone'), timestamp) AS initial_geoip_time_zone,
        argMinState(JSONExtractString(properties, '$referring_domain'), timestamp) AS initial_referring_domain,
        argMinState(JSONExtractString(properties, 'utm_source'), timestamp) AS initial_utm_source,
        argMinState(JSONExtractString(properties, 'utm_campaign'), timestamp) AS initial_utm_campaign,
        argMinState(JSONExtractString(properties, 'utm_medium'), timestamp) AS initial_utm_medium,
        argMinState(JSONExtractString(properties, 'utm_term'), timestamp) AS initial_utm_term,
        argMinState(JSONExtractString(properties, 'utm_content'), timestamp) AS initial_utm_content,
        argMinState(JSONExtractString(properties, 'gclid'), timestamp) AS initial_gclid,
        argMinState(JSONExtractString(properties, 'gad_source'), timestamp) AS initial_gad_source,
        argMinState(JSONExtractString(properties, 'gclsrc'), timestamp) AS initial_gclsrc,
        argMinState(JSONExtractString(properties, 'dclid'), timestamp) AS initial_dclid,
        argMinState(JSONExtractString(properties, 'gbraid'), timestamp) AS initial_gbraid,
        argMinState(JSONExtractString(properties, 'wbraid'), timestamp) AS initial_wbraid,
        argMinState(JSONExtractString(properties, 'fbclid'), timestamp) AS initial_fbclid,
        argMinState(JSONExtractString(properties, 'msclkid'), timestamp) AS initial_msclkid,
        argMinState(JSONExtractString(properties, 'twclid'), timestamp) AS initial_twclid,
        argMinState(JSONExtractString(properties, 'li_fat_id'), timestamp) AS initial_li_fat_id,
        argMinState(JSONExtractString(properties, 'mc_cid'), timestamp) AS initial_mc_cid,
        argMinState(JSONExtractString(properties, 'igshid'), timestamp) AS initial_igshid,
        argMinState(JSONExtractString(properties, 'ttclid'), timestamp) AS initial_ttclid,
        argMinState(JSONExtractString(properties, 'epik'), timestamp) AS initial_epik,
        argMinState(JSONExtractString(properties, 'qclid'), timestamp) AS initial_qclid,
        argMinState(JSONExtractString(properties, 'sccid'), timestamp) AS initial_sccid,
        argMinState(JSONExtractString(properties, '_kx'), timestamp) AS initial__kx,
        argMinState(JSONExtractString(properties, 'irclid'), timestamp) AS initial_irclid,
        sumIf(1, event = '$pageview') AS pageview_count,
        uniqState(CAST(if(event = '$pageview', uuid, NULL), 'Nullable(UUID)')) AS pageview_uniq,
        sumIf(1, event = '$autocapture') AS autocapture_count,
        uniqState(CAST(if(event = '$autocapture', uuid, NULL), 'Nullable(UUID)')) AS autocapture_uniq,
        sumIf(1, event = '$screen') AS screen_count,
        uniqState(CAST(if(event = '$screen', uuid, NULL), 'Nullable(UUID)')) AS screen_uniq,
        false AS maybe_has_session_replay,
        uniqUpToState(1)(CAST(if((event = '$pageview') OR (event = '$screen') OR (event = '$autocapture'), uuid, NULL), 'Nullable(UUID)')) AS page_screen_autocapture_uniq_up_to,
        argMinState(accurateCastOrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, '$web_vitals_LCP_value'), ''), 'null'), '^"|"$', ''), 'Float64'), timestamp) AS vitals_lcp
    FROM ${var.database}.sharded_events
    WHERE bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(`$session_id`, 'UUID')), 76), 15) = 7
    GROUP BY
        team_id,
        toStartOfHour(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000))),
        cityHash64(session_id_v7),
        session_id_v7
  SQL
  override = try(local.deployment.overrides["raw_sessions_mv"], {})

  depends_on = [
    module.sharded_raw_sessions_family,
  ]
}

# Distributed tables, views and dictionaries that queries read from.


module "raw_sessions_v" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "raw_sessions_v")
  database = var.database
  name     = "raw_sessions_v"
  query    = <<-SQL
    SELECT
        session_id_v7,
        fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000)) AS session_timestamp,
        team_id,
        argMaxMerge(distinct_id) AS distinct_id,
        min(min_timestamp) AS min_timestamp,
        max(max_timestamp) AS max_timestamp,
        max(max_inserted_at) AS max_inserted_at,
        arrayDistinct(arrayFlatten(groupArray(urls))) AS urls,
        argMinMerge(entry_url) AS entry_url,
        argMaxMerge(end_url) AS end_url,
        argMaxMerge(last_external_click_url) AS last_external_click_url,
        argMinMerge(initial_browser) AS initial_browser,
        argMinMerge(initial_browser_version) AS initial_browser_version,
        argMinMerge(initial_os) AS initial_os,
        argMinMerge(initial_os_version) AS initial_os_version,
        argMinMerge(initial_device_type) AS initial_device_type,
        argMinMerge(initial_viewport_width) AS initial_viewport_width,
        argMinMerge(initial_viewport_height) AS initial_viewport_height,
        argMinMerge(initial_geoip_country_code) AS initial_geoip_country_code,
        argMinMerge(initial_geoip_subdivision_1_code) AS initial_geoip_subdivision_1_code,
        argMinMerge(initial_geoip_subdivision_1_name) AS initial_geoip_subdivision_1_name,
        argMinMerge(initial_geoip_subdivision_city_name) AS initial_geoip_subdivision_city_name,
        argMinMerge(initial_geoip_time_zone) AS initial_geoip_time_zone,
        argMinMerge(initial_utm_source) AS initial_utm_source,
        argMinMerge(initial_utm_campaign) AS initial_utm_campaign,
        argMinMerge(initial_utm_medium) AS initial_utm_medium,
        argMinMerge(initial_utm_term) AS initial_utm_term,
        argMinMerge(initial_utm_content) AS initial_utm_content,
        argMinMerge(initial_referring_domain) AS initial_referring_domain,
        argMinMerge(initial_gclid) AS initial_gclid,
        argMinMerge(initial_gad_source) AS initial_gad_source,
        argMinMerge(initial_gclsrc) AS initial_gclsrc,
        argMinMerge(initial_dclid) AS initial_dclid,
        argMinMerge(initial_gbraid) AS initial_gbraid,
        argMinMerge(initial_wbraid) AS initial_wbraid,
        argMinMerge(initial_fbclid) AS initial_fbclid,
        argMinMerge(initial_msclkid) AS initial_msclkid,
        argMinMerge(initial_twclid) AS initial_twclid,
        argMinMerge(initial_li_fat_id) AS initial_li_fat_id,
        argMinMerge(initial_mc_cid) AS initial_mc_cid,
        argMinMerge(initial_igshid) AS initial_igshid,
        argMinMerge(initial_ttclid) AS initial_ttclid,
        argMinMerge(initial__kx) AS initial__kx,
        argMinMerge(initial_irclid) AS initial_irclid,
        sum(pageview_count) AS pageview_count,
        uniqMerge(pageview_uniq) AS pageview_uniq,
        sum(autocapture_count) AS autocapture_count,
        uniqMerge(autocapture_uniq) AS autocapture_uniq,
        sum(screen_count) AS screen_count,
        uniqMerge(screen_uniq) AS screen_uniq,
        max(maybe_has_session_replay) AS maybe_has_session_replay,
        uniqUpToMerge(1)(page_screen_autocapture_uniq_up_to) AS page_screen_autocapture_uniq_up_to,
        argMinMerge(vitals_lcp) AS vitals_lcp
    FROM ${var.database}.raw_sessions
    GROUP BY
        session_id_v7,
        team_id
  SQL
  override = try(local.deployment.overrides["raw_sessions_v"], {})

  depends_on = [
    module.sharded_raw_sessions_family,
  ]
}


module "raw_sessions_v3_v" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "raw_sessions_v3_v")
  database = var.database
  name     = "raw_sessions_v3_v"
  query    = <<-SQL
    SELECT
        session_id_v7,
        session_timestamp,
        team_id,
        argMaxMerge(distinct_id) AS distinct_id,
        groupUniqArrayMerge(distinct_ids) AS distinct_ids,
        min(min_timestamp) AS min_timestamp,
        max(max_timestamp) AS max_timestamp,
        max(max_inserted_at) AS max_inserted_at,
        groupUniqArrayArray(2000)(urls) AS urls,
        argMinMerge(entry_url) AS entry_url,
        argMaxMerge(end_url) AS end_url,
        argMaxMerge(last_external_click_url) AS last_external_click_url,
        argMinMerge(browser) AS browser,
        argMinMerge(browser_version) AS browser_version,
        argMinMerge(os) AS os,
        argMinMerge(os_version) AS os_version,
        argMinMerge(device_type) AS device_type,
        argMinMerge(viewport_width) AS viewport_width,
        argMinMerge(viewport_height) AS viewport_height,
        argMinMerge(geoip_country_code) AS geoip_country_code,
        argMinMerge(geoip_subdivision_1_code) AS geoip_subdivision_1_code,
        argMinMerge(geoip_subdivision_1_name) AS geoip_subdivision_1_name,
        argMinMerge(geoip_subdivision_city_name) AS geoip_subdivision_city_name,
        argMinMerge(geoip_time_zone) AS geoip_time_zone,
        argMinMerge(entry_utm_source) AS entry_utm_source,
        argMinMerge(entry_utm_campaign) AS entry_utm_campaign,
        argMinMerge(entry_utm_medium) AS entry_utm_medium,
        argMinMerge(entry_utm_term) AS entry_utm_term,
        argMinMerge(entry_utm_content) AS entry_utm_content,
        argMinMerge(entry_referring_domain) AS entry_referring_domain,
        argMinMerge(entry_gclid) AS entry_gclid,
        argMinMerge(entry_gad_source) AS entry_gad_source,
        argMinMerge(entry_fbclid) AS entry_fbclid,
        argMinMerge(entry_has_gclid) AS entry_has_gclid,
        argMinMerge(entry_has_fbclid) AS entry_has_fbclid,
        argMinMerge(entry_ad_ids_map) AS entry_ad_ids_map,
        argMinMerge(entry_ad_ids_set) AS entry_ad_ids_set,
        argMinMerge(entry_channel_type_properties) AS entry_channel_type_properties,
        uniqExactMerge(pageview_uniq) AS pageview_uniq,
        uniqExactMerge(autocapture_uniq) AS autocapture_uniq,
        uniqExactMerge(screen_uniq) AS screen_uniq,
        uniqUpToMerge(1)(page_screen_uniq_up_to) AS page_screen_uniq_up_to,
        max(has_autocapture) AS has_autocapture,
        groupUniqArrayArray(10000)(flag_key_values) AS flag_key_values,
        groupUniqArrayArray(flag_keys) AS flag_keys,
        groupUniqArrayArray(2000)(event_names) AS event_names,
        groupUniqArrayArray(100)(hosts) AS hosts,
        groupUniqArrayArray(10)(emails) AS emails,
        max(has_replay_events) AS has_replay_events
    FROM ${var.database}.raw_sessions_v3
    GROUP BY
        session_id_v7,
        session_timestamp,
        team_id
  SQL
  override = try(local.deployment.overrides["raw_sessions_v3_v"], {})

  depends_on = [
    module.sharded_raw_sessions_v3_family,
  ]
}

# Objects only the test suite uses, such as materialized views that stand in for the kafka pipeline.

module "raw_sessions_v3_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "raw_sessions_v3_mv")
  database = var.database
  name     = "raw_sessions_v3_mv"
  to_table = "${var.database}.writable_raw_sessions_v3"
  query    = <<-SQL
    WITH
        JSONExtract(properties, 'Tuple(\n            `$current_url` Nullable(String),\n            `$external_click_url` Nullable(String),\n            `$browser` Nullable(String),\n            `$browser_version` Nullable(String),\n            `$os` Nullable(String),\n            `$os_version` Nullable(String),\n            `$device_type` Nullable(String),\n            `$viewport_width` Nullable(Int64),\n            `$viewport_height` Nullable(Int64),\n            `$geoip_country_code` Nullable(String),\n            `$geoip_subdivision_1_code` Nullable(String),\n            `$geoip_subdivision_1_name` Nullable(String),\n            `$geoip_subdivision_city_name` Nullable(String),\n            `$geoip_time_zone` Nullable(String),\n            `$referring_domain` Nullable(String),\n            `utm_source` Nullable(String),\n            `utm_campaign` Nullable(String),\n            `utm_medium` Nullable(String),\n            `utm_term` Nullable(String),\n            `utm_content` Nullable(String),\n            `gclid` Nullable(String),\n            `gad_source` Nullable(String),\n            `fbclid` Nullable(String),\n            `$host` Nullable(String),\n            `gclsrc` Nullable(String),\n            `dclid` Nullable(String),\n            `gbraid` Nullable(String),\n            `wbraid` Nullable(String),\n            `msclkid` Nullable(String),\n            `twclid` Nullable(String),\n            `li_fat_id` Nullable(String),\n            `mc_cid` Nullable(String),\n            `igshid` Nullable(String),\n            `ttclid` Nullable(String),\n            `epik` Nullable(String),\n            `qclid` Nullable(String),\n            `sccid` Nullable(String),\n            `_kx` Nullable(String),\n            `irclid` Nullable(String)\n        )') AS p,
        JSONExtractString(person_properties, 'email') AS _person_email,
        tupleElement(p, '$current_url') AS _current_url,
        tupleElement(p, '$external_click_url') AS _external_click_url,
        tupleElement(p, '$browser') AS _browser,
        tupleElement(p, '$browser_version') AS _browser_version,
        tupleElement(p, '$os') AS _os,
        tupleElement(p, '$os_version') AS _os_version,
        tupleElement(p, '$device_type') AS _device_type,
        tupleElement(p, '$viewport_width') AS _viewport_width,
        tupleElement(p, '$viewport_height') AS _viewport_height,
        tupleElement(p, '$geoip_country_code') AS _geoip_country_code,
        tupleElement(p, '$geoip_subdivision_1_code') AS _geoip_subdivision_1_code,
        tupleElement(p, '$geoip_subdivision_1_name') AS _geoip_subdivision_1_name,
        tupleElement(p, '$geoip_subdivision_city_name') AS _geoip_subdivision_city_name,
        tupleElement(p, '$geoip_time_zone') AS _geoip_time_zone,
        tupleElement(p, '$referring_domain') AS _referring_domain,
        tupleElement(p, 'utm_source') AS _utm_source,
        tupleElement(p, 'utm_campaign') AS _utm_campaign,
        tupleElement(p, 'utm_medium') AS _utm_medium,
        tupleElement(p, 'utm_term') AS _utm_term,
        tupleElement(p, 'utm_content') AS _utm_content,
        tupleElement(p, 'gclid') AS _gclid,
        tupleElement(p, 'gad_source') AS _gad_source,
        tupleElement(p, 'fbclid') AS _fbclid,
        tupleElement(p, 'gclsrc') AS gclsrc,
        tupleElement(p, 'dclid') AS dclid,
        tupleElement(p, 'gbraid') AS gbraid,
        tupleElement(p, 'wbraid') AS wbraid,
        tupleElement(p, 'msclkid') AS msclkid,
        tupleElement(p, 'twclid') AS twclid,
        tupleElement(p, 'li_fat_id') AS li_fat_id,
        tupleElement(p, 'mc_cid') AS mc_cid,
        tupleElement(p, 'igshid') AS igshid,
        tupleElement(p, 'ttclid') AS ttclid,
        tupleElement(p, 'epik') AS epik,
        tupleElement(p, 'qclid') AS qclid,
        tupleElement(p, 'sccid') AS sccid,
        tupleElement(p, '_kx') AS _kx,
        tupleElement(p, 'irclid') AS irclid,
        CAST(mapFilter((k, v) -> (v IS NOT NULL), map('gclsrc', gclsrc, 'dclid', dclid, 'gbraid', gbraid, 'wbraid', wbraid, 'msclkid', msclkid, 'twclid', twclid, 'li_fat_id', li_fat_id, 'mc_cid', mc_cid, 'igshid', igshid, 'ttclid', ttclid, 'epik', epik, 'qclid', qclid, 'sccid', sccid, '_kx', _kx, 'irclid', irclid)), 'Map(String, String)') AS ad_ids_map,
        CAST(arrayFilter(x -> (x IS NOT NULL), [if(gclsrc IS NOT NULL, 'gclsrc', NULL), if(dclid IS NOT NULL, 'dclid', NULL), if(gbraid IS NOT NULL, 'gbraid', NULL), if(wbraid IS NOT NULL, 'wbraid', NULL), if(msclkid IS NOT NULL, 'msclkid', NULL), if(twclid IS NOT NULL, 'twclid', NULL), if(li_fat_id IS NOT NULL, 'li_fat_id', NULL), if(mc_cid IS NOT NULL, 'mc_cid', NULL), if(igshid IS NOT NULL, 'igshid', NULL), if(ttclid IS NOT NULL, 'ttclid', NULL), if(epik IS NOT NULL, 'epik', NULL), if(qclid IS NOT NULL, 'qclid', NULL), if(sccid IS NOT NULL, 'sccid', NULL), if(_kx IS NOT NULL, '_kx', NULL), if(irclid IS NOT NULL, 'irclid', NULL)]), 'Array(String)') AS ad_ids_set,
        tupleElement(p, '$host') AS _host,
        if((event = '$pageview') OR (event = '$screen'), timestamp, timestamp + toIntervalYear(1)) AS pageview_prio_timestamp_min,
        if((event = '$pageview') OR (event = '$screen'), timestamp, timestamp - toIntervalYear(1)) AS pageview_prio_timestamp_max
    SELECT
        team_id,
        `$session_id_uuid` AS session_id_v7,
        initializeAggregation('argMaxState', source_table.distinct_id, timestamp) AS distinct_id,
        initializeAggregation('groupUniqArrayState', source_table.distinct_id) AS distinct_ids,
        timestamp AS min_timestamp,
        timestamp AS max_timestamp,
        inserted_at AS max_inserted_at,
        if((_current_url IS NOT NULL) AND ((event = '$pageview') OR (event = '$screen')), [_current_url], []) AS urls,
        initializeAggregation('argMinState', _current_url, pageview_prio_timestamp_min) AS entry_url,
        initializeAggregation('argMaxState', _current_url, pageview_prio_timestamp_max) AS end_url,
        initializeAggregation('argMaxState', _external_click_url, timestamp) AS last_external_click_url,
        initializeAggregation('argMinState', _browser, timestamp) AS browser,
        initializeAggregation('argMinState', _browser_version, timestamp) AS browser_version,
        initializeAggregation('argMinState', _os, timestamp) AS os,
        initializeAggregation('argMinState', _os_version, timestamp) AS os_version,
        initializeAggregation('argMinState', _device_type, timestamp) AS device_type,
        initializeAggregation('argMinState', _viewport_width, timestamp) AS viewport_width,
        initializeAggregation('argMinState', _viewport_height, timestamp) AS viewport_height,
        initializeAggregation('argMinState', _geoip_country_code, timestamp) AS geoip_country_code,
        initializeAggregation('argMinState', _geoip_subdivision_1_code, timestamp) AS geoip_subdivision_1_code,
        initializeAggregation('argMinState', _geoip_subdivision_1_name, timestamp) AS geoip_subdivision_1_name,
        initializeAggregation('argMinState', _geoip_subdivision_city_name, timestamp) AS geoip_subdivision_city_name,
        initializeAggregation('argMinState', _geoip_time_zone, timestamp) AS geoip_time_zone,
        initializeAggregation('argMinState', _referring_domain, pageview_prio_timestamp_min) AS entry_referring_domain,
        initializeAggregation('argMinState', _utm_source, pageview_prio_timestamp_min) AS entry_utm_source,
        initializeAggregation('argMinState', _utm_campaign, pageview_prio_timestamp_min) AS entry_utm_campaign,
        initializeAggregation('argMinState', _utm_medium, pageview_prio_timestamp_min) AS entry_utm_medium,
        initializeAggregation('argMinState', _utm_term, pageview_prio_timestamp_min) AS entry_utm_term,
        initializeAggregation('argMinState', _utm_content, pageview_prio_timestamp_min) AS entry_utm_content,
        initializeAggregation('argMinState', _gclid, pageview_prio_timestamp_min) AS entry_gclid,
        initializeAggregation('argMinState', _gad_source, pageview_prio_timestamp_min) AS entry_gad_source,
        initializeAggregation('argMinState', _fbclid, pageview_prio_timestamp_min) AS entry_fbclid,
        initializeAggregation('argMinState', _gclid IS NOT NULL, pageview_prio_timestamp_min) AS entry_has_gclid,
        initializeAggregation('argMinState', _fbclid IS NOT NULL, pageview_prio_timestamp_min) AS entry_has_fbclid,
        initializeAggregation('argMinState', ad_ids_map, pageview_prio_timestamp_min) AS entry_ad_ids_map,
        initializeAggregation('argMinState', ad_ids_set, pageview_prio_timestamp_min) AS entry_ad_ids_set,
        initializeAggregation('argMinState', tuple(_utm_source, _utm_medium, _utm_campaign, _referring_domain, _gclid IS NOT NULL, _fbclid IS NOT NULL, _gad_source), pageview_prio_timestamp_min) AS entry_channel_type_properties,
        initializeAggregation('uniqExactState', if(event = '$pageview', uuid, NULL)) AS pageview_uniq,
        initializeAggregation('uniqExactState', if(event = '$autocapture', uuid, NULL)) AS autocapture_uniq,
        initializeAggregation('uniqExactState', if(event = '$screen', uuid, NULL)) AS screen_uniq,
        initializeAggregation('uniqUpToState(1)', if((event = '$pageview') OR (event = '$screen'), uuid, NULL)) AS page_screen_uniq_up_to,
        event = '$autocapture' AS has_autocapture,
        arrayMap((k, v) -> concat(k, '=', v), mapKeys(properties_group_feature_flags), mapValues(properties_group_feature_flags)) AS flag_key_values,
        mapKeys(properties_group_feature_flags) AS flag_keys,
        [event] AS event_names,
        if((_host IS NOT NULL) AND (_host != ''), [_host], []) AS hosts,
        if((_person_email IS NOT NULL) AND (_person_email != ''), [_person_email], []) AS emails,
        false AS has_replay_events
    FROM ${var.database}.sharded_events AS source_table
    WHERE (bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(`$session_id`, 'UUID')), 76), 15) = 7) AND true
  SQL
  override = try(local.deployment.overrides["raw_sessions_v3_mv"], {})

  depends_on = [
    module.sharded_raw_sessions_v3_family,
  ]
}

module "raw_sessions_v3_recordings_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "raw_sessions_v3_recordings_mv")
  database = var.database
  name     = "raw_sessions_v3_recordings_mv"
  to_table = "${var.database}.writable_raw_sessions_v3"
  query    = <<-SQL
    WITH
        min_first_timestamp AS timestamp,
        CAST(fromUnixTimestamp64Milli(9223372036854775), 'DateTime64(6)') AS max_ts_64,
        CAST(fromUnixTimestamp64Milli(-9223372036854775), 'DateTime64(6)') AS min_ts_64,
        CAST(NULL, 'Nullable(String)') AS null_s,
        CAST(NULL, 'Nullable(Int64)') AS null_i64,
        CAST(NULL, 'Nullable(UUID)') AS null_uuid
    SELECT
        team_id,
        toUInt128(accurateCast(session_id, 'UUID')) AS session_id_v7,
        fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80))) AS session_timestamp,
        initializeAggregation('argMaxState', source_table.distinct_id, min_ts_64) AS distinct_id,
        initializeAggregation('groupUniqArrayState', source_table.distinct_id) AS distinct_ids,
        timestamp AS min_timestamp,
        timestamp AS max_timestamp,
        fromUnixTimestamp(0) AS max_inserted_at,
        CAST([], 'Array(String)') AS urls,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_url,
        initializeAggregation('argMaxState', null_s, min_ts_64) AS end_url,
        initializeAggregation('argMaxState', null_s, min_ts_64) AS last_external_click_url,
        initializeAggregation('argMinState', null_s, max_ts_64) AS browser,
        initializeAggregation('argMinState', null_s, max_ts_64) AS browser_version,
        initializeAggregation('argMinState', null_s, max_ts_64) AS os,
        initializeAggregation('argMinState', null_s, max_ts_64) AS os_version,
        initializeAggregation('argMinState', null_s, max_ts_64) AS device_type,
        initializeAggregation('argMinState', null_i64, max_ts_64) AS viewport_width,
        initializeAggregation('argMinState', null_i64, max_ts_64) AS viewport_height,
        initializeAggregation('argMinState', null_s, max_ts_64) AS geoip_country_code,
        initializeAggregation('argMinState', null_s, max_ts_64) AS geoip_subdivision_1_code,
        initializeAggregation('argMinState', null_s, max_ts_64) AS geoip_subdivision_1_name,
        initializeAggregation('argMinState', null_s, max_ts_64) AS geoip_subdivision_city_name,
        initializeAggregation('argMinState', null_s, max_ts_64) AS geoip_time_zone,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_referring_domain,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_utm_source,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_utm_campaign,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_utm_medium,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_utm_term,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_utm_content,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_gclid,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_gad_source,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_fbclid,
        initializeAggregation('argMinState', false, max_ts_64) AS entry_has_gclid,
        initializeAggregation('argMinState', false, max_ts_64) AS entry_has_fbclid,
        initializeAggregation('argMinState', CAST(map(), 'Map(String, String)'), max_ts_64) AS entry_ad_ids_map,
        initializeAggregation('argMinState', CAST([], 'Array(String)'), max_ts_64) AS entry_ad_ids_set,
        initializeAggregation('argMinState', tuple(null_s, null_s, null_s, null_s, false, false, null_s), max_ts_64) AS entry_channel_type_properties,
        initializeAggregation('uniqExactState', null_uuid) AS pageview_uniq,
        initializeAggregation('uniqExactState', null_uuid) AS autocapture_uniq,
        initializeAggregation('uniqExactState', null_uuid) AS screen_uniq,
        initializeAggregation('uniqUpToState(1)', null_uuid) AS page_screen_uniq_up_to,
        false AS has_autocapture,
        CAST([], 'Array(String)') AS flag_key_values,
        CAST([], 'Array(String)') AS flag_keys,
        CAST([], 'Array(String)') AS event_names,
        CAST([], 'Array(String)') AS hosts,
        CAST([], 'Array(String)') AS emails,
        true AS has_replay_events
    FROM ${var.database}.sharded_session_replay_events AS source_table
    WHERE (bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(session_id, 'UUID')), 76), 15) = 7) AND true
  SQL
  override = try(local.deployment.overrides["raw_sessions_v3_recordings_mv"], {})

  depends_on = [
    module.sharded_raw_sessions_v3_family,
  ]
}

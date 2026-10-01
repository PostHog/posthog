module "sharded_raw_sessions_family" {
  source = "../../lib/table_family"

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
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_raw_sessions", "raw_sessions", "writable_raw_sessions"], name) }
  })
}

module "sharded_raw_sessions_v3_family" {
  source = "../../lib/table_family"

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
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_raw_sessions_v3", "raw_sessions_v3", "writable_raw_sessions_v3"], name) }
  })
}

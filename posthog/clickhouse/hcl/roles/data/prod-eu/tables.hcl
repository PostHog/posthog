# prod-eu data cluster: objects only prod-eu runs, and the deltas it applies to the cloud shape.
database "posthog" {
  table "asyncdeletion" {
    override = true
    order_by     = ["deletion_type", "delete_verified_at"]
    partition_by = "toYYYYMM(created_at)"
    settings = {
      index_granularity = "8192"
    }
    column "id" {
      type = "UInt64"
    }
    column "deletion_type" {
      type = "UInt8"
    }
    column "key" {
      type = "String"
    }
    column "group_type_index" {
      type = "UInt64"
    }
    column "created_at" {
      type = "DateTime"
    }
    column "delete_verified_at" {
      type = "DateTime"
    }
    column "created_by_id" {
      type = "UInt64"
    }
    column "team_id" {
      type = "UInt64"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/asyncdeletion"
      replica_name = "{replica}-{shard}"
    }
  }

  table "kafka_session_replay_features" {
    # The ingestion nodes declare this name too, for the table they write through.
    # A data node holds a different object under it, so this restates rather than
    # redeclares.
    override = true
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "batch_id" {
      type = "String"
    }
    column "first_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "last_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "event_count" {
      type = "Int64"
    }
    column "mouse_position_count" {
      type = "Int64"
    }
    column "mouse_sum_x" {
      type = "Float64"
    }
    column "mouse_sum_x_squared" {
      type = "Float64"
    }
    column "mouse_sum_y" {
      type = "Float64"
    }
    column "mouse_sum_y_squared" {
      type = "Float64"
    }
    column "mouse_distance_traveled" {
      type = "Float64"
    }
    column "mouse_direction_change_count" {
      type = "Int64"
    }
    column "mouse_velocity_sum" {
      type = "Float64"
    }
    column "mouse_velocity_sum_of_squares" {
      type = "Float64"
    }
    column "mouse_velocity_count" {
      type = "Int64"
    }
    column "scroll_event_count" {
      type = "Int64"
    }
    column "total_scroll_magnitude" {
      type = "Float64"
    }
    column "scroll_direction_reversal_count" {
      type = "Int64"
    }
    column "rapid_scroll_reversal_count" {
      type = "Int64"
    }
    column "click_count" {
      type = "Int64"
    }
    column "keypress_count" {
      type = "Int64"
    }
    column "mouse_activity_count" {
      type = "Int64"
    }
    column "rage_click_count" {
      type = "Int64"
    }
    column "dead_click_count" {
      type = "Int64"
    }
    column "inter_action_gap_count" {
      type = "Int64"
    }
    column "inter_action_gap_sum_ms" {
      type = "Float64"
    }
    column "inter_action_gap_sum_of_squares_ms" {
      type = "Float64"
    }
    column "max_idle_gap_ms" {
      type = "Float64"
    }
    column "quick_back_count" {
      type = "Int64"
    }
    column "page_visit_count" {
      type = "Int64"
    }
    column "visited_urls" {
      type = "Array(String)"
    }
    column "console_error_count" {
      type = "Int64"
    }
    column "console_error_after_click_count" {
      type = "Int64"
    }
    column "network_request_count" {
      type = "Int64"
    }
    column "network_failed_request_count" {
      type = "Int64"
    }
    column "network_request_duration_sum" {
      type = "Float64"
    }
    column "network_request_duration_sum_of_squares" {
      type = "Float64"
    }
    column "network_request_duration_count" {
      type = "Int64"
    }
    column "max_scroll_y" {
      type = "Float64"
    }
    column "click_target_ids" {
      type = "Array(Int64)"
    }
    column "text_selection_count" {
      type = "Int64"
    }
    column "is_deleted" {
      type = "UInt8"
    }
    engine "kafka" {
      collection = "msk_cluster"
      topic_list = "clickhouse_session_replay_features"
      group_name = "group1"
      format     = "JSONEachRow"
    }
  }

  table "metrics_query_log" {
    order_by     = ["toDate(timestamp)", "team_id", "query_type"]
    partition_by = "toYYYYMM(timestamp)"
    settings = {
      index_granularity = "8192"
    }
    column "host" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime"
    }
    column "query_duration_ms" {
      type = "UInt64"
    }
    column "read_rows" {
      type = "UInt64"
    }
    column "read_bytes" {
      type = "UInt64"
    }
    column "result_rows" {
      type = "UInt64"
    }
    column "result_bytes" {
      type = "UInt64"
    }
    column "memory_usage" {
      type = "UInt64"
    }
    column "is_initial_query" {
      type = "UInt8"
    }
    column "exception_code" {
      type = "Int32"
    }
    column "team_id" {
      type = "Int64"
    }
    column "team_events_last_month" {
      type = "UInt64"
    }
    column "user_id" {
      type = "Int64"
    }
    column "kind" {
      type = "String"
    }
    column "query_type" {
      type = "String"
    }
    column "client_query_id" {
      type = "String"
    }
    column "id" {
      type = "String"
    }
    column "route_id" {
      type = "String"
    }
    column "query_time_range_days" {
      type = "Int64"
    }
    column "has_joins" {
      type = "UInt8"
    }
    column "has_json_operations" {
      type = "UInt8"
    }
    column "filter_by_type" {
      type = "Array(String)"
    }
    column "breakdown_by" {
      type = "Array(String)"
    }
    column "entity_math" {
      type = "Array(String)"
    }
    column "filter" {
      type = "String"
    }
    column "tables" {
      type = "Array(LowCardinality(String))"
    }
    column "columns" {
      type = "Array(LowCardinality(String))"
    }
    column "query" {
      type = "String"
    }
    column "log_comment" {
      type = "String"
    }
    column "is_exception" {
      type = "UInt8"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.metrics_query_log"
      replica_name = "{replica}-{shard}"
    }
  }

  table "new_writable_raw_sessions" {
    column "team_id" {
      type = "Int64"
    }
    column "session_id_v7" {
      type = "UInt128"
    }
    column "distinct_id" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "min_timestamp" {
      type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "max_inserted_at" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "urls" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "entry_url" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "end_url" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "last_external_click_url" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "initial_browser" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_browser_version" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_os" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_os_version" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_device_type" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_viewport_width" {
      type = "AggregateFunction(argMin, Int64, DateTime64(6, 'UTC'))"
    }
    column "initial_viewport_height" {
      type = "AggregateFunction(argMin, Int64, DateTime64(6, 'UTC'))"
    }
    column "initial_geoip_country_code" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_geoip_subdivision_1_code" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_geoip_subdivision_1_name" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_geoip_subdivision_city_name" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_geoip_time_zone" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_referring_domain" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_source" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_campaign" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_medium" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_term" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_content" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gad_source" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gclsrc" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_dclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gbraid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_wbraid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_fbclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_msclkid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_twclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_li_fat_id" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_mc_cid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_igshid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_ttclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_irclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "pageview_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "pageview_uniq" {
      type = "AggregateFunction(uniq, Nullable(UUID))"
    }
    column "autocapture_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "autocapture_uniq" {
      type = "AggregateFunction(uniq, Nullable(UUID))"
    }
    column "screen_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "screen_uniq" {
      type = "AggregateFunction(uniq, Nullable(UUID))"
    }
    column "maybe_has_session_replay" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "page_screen_autocapture_uniq_up_to" {
      type = "AggregateFunction(uniqUpTo(1), Nullable(UUID))"
    }
    column "vitals_lcp" {
      type = "AggregateFunction(argMin, Nullable(Float64), DateTime64(6, 'UTC'))"
    }
    column "initial__kx" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_raw_sessions"
      sharding_key    = "cityHash64(session_id_v7)"
    }
  }

  patch_table "new_writable_sessions" {
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_sessions"
      sharding_key    = "sipHash64(session_id)"
    }
  }

  table "pending_person_deletes_reporting" {
    override = true
    order_by = ["team_id", "deletion_type", "key"]
    settings = {
      index_granularity = "8192"
    }
    column "id" {
      type = "UInt64"
    }
    column "deletion_type" {
      type = "UInt8"
    }
    column "key" {
      type = "String"
    }
    column "group_type_index" {
      type = "Nullable(String)"
    }
    column "created_at" {
      type = "DateTime"
    }
    column "delete_verified_at" {
      type = "Nullable(DateTime)"
    }
    column "created_by_id" {
      type = "Nullable(String)"
    }
    column "team_id" {
      type = "Int64"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/pending_person_deletes_reporting"
      replica_name = "{shard}-{replica}"
    }
  }

  table "person" {
    override = true
    order_by = ["team_id", "id"]
    settings = {
      index_granularity = "8192"
    }
    column "id" {
      type = "UUID"
    }
    column "created_at" {
      type = "DateTime64(3)"
    }
    column "team_id" {
      type = "Int64"
    }
    column "properties" {
      type = "String"
    }
    column "is_identified" {
      type = "Int8"
    }
    column "is_deleted" {
      type    = "Int8"
      default = "0"
    }
    column "version" {
      type = "UInt64"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "last_seen_at" {
      type = "Nullable(DateTime64(3))"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.person"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  table "person_collapsing" {
    override = true
    order_by = ["team_id", "id"]
    settings = {
      index_granularity = "8192"
    }
    column "id" {
      type = "UUID"
    }
    column "created_at" {
      type = "DateTime64(3)"
    }
    column "team_id" {
      type = "Int64"
    }
    column "properties" {
      type = "String"
    }
    column "is_identified" {
      type = "Int8"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_sign" {
      type = "Int8"
    }
    engine "replicated_collapsing_merge_tree" {
      zoo_path     = "/clickhouse/prod/tables/noshard/posthog.person_collapsing"
      replica_name = "{replica}-{shard}"
      sign_column  = "_sign"
    }
  }

  table "sharded_precalculated_person_properties" {
    override = true
    order_by = ["team_id", "condition", "distinct_id"]
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    column "condition" {
      type = "String"
    }
    column "matches" {
      type = "Bool"
    }
    column "source" {
      type = "String"
    }
    column "_timestamp" {
      type = "DateTime64(6)"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.sharded_precalculated_person_properties"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }

  table "sharded_raw_sessions_v3" {
    override = true
    order_by     = ["team_id", "session_timestamp", "session_id_v7"]
    partition_by = "toYYYYMM(session_timestamp)"
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int64"
    }
    column "session_id_v7" {
      type = "UInt128"
    }
    column "session_timestamp" {
      type         = "DateTime64(3)"
      materialized = "fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80)))"
    }
    column "distinct_id" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "distinct_ids" {
      type = "AggregateFunction(groupUniqArray, String)"
    }
    column "min_timestamp" {
      type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "max_inserted_at" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "urls" {
      type = "SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String))"
    }
    column "entry_url" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "end_url" {
      type = "AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "last_external_click_url" {
      type = "AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "browser" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "browser_version" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "os" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "os_version" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "device_type" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "viewport_width" {
      type = "AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC'))"
    }
    column "viewport_height" {
      type = "AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC'))"
    }
    column "geoip_country_code" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_subdivision_1_code" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_subdivision_1_name" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_subdivision_city_name" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_time_zone" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_referring_domain" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_source" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_campaign" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_medium" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_term" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_content" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_gclid" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_gad_source" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_fbclid" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_has_gclid" {
      type = "AggregateFunction(argMin, Bool, DateTime64(6, 'UTC'))"
    }
    column "entry_has_fbclid" {
      type = "AggregateFunction(argMin, Bool, DateTime64(6, 'UTC'))"
    }
    column "entry_ad_ids_map" {
      type = "AggregateFunction(argMin, Map(String, String), DateTime64(6, 'UTC'))"
    }
    column "entry_ad_ids_set" {
      type = "AggregateFunction(argMin, Array(String), DateTime64(6, 'UTC'))"
    }
    column "entry_channel_type_properties" {
      type = "AggregateFunction(argMin, Tuple(Nullable(String), Nullable(String), Nullable(String), Nullable(String), Bool, Bool, Nullable(String)), DateTime64(6, 'UTC'))"
    }
    column "pageview_uniq" {
      type = "AggregateFunction(uniqExact, Nullable(UUID))"
    }
    column "autocapture_uniq" {
      type = "AggregateFunction(uniqExact, Nullable(UUID))"
    }
    column "screen_uniq" {
      type = "AggregateFunction(uniqExact, Nullable(UUID))"
    }
    column "page_screen_uniq_up_to" {
      type = "AggregateFunction(uniqUpTo(1), Nullable(UUID))"
    }
    column "has_autocapture" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "flag_values" {
      type = "AggregateFunction(groupUniqArrayMap, Map(String, String))"
    }
    column "flag_keys" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "event_names" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "has_replay_events" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    index "event_names_bloom_filter" {
      expr        = "event_names"
      type        = "bloom_filter()"
      granularity = 1
    }
    index "flag_keys_bloom_filter" {
      expr        = "flag_keys"
      type        = "bloom_filter()"
      granularity = 1
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.raw_sessions_v3"
      replica_name = "{replica}"
    }
  }

  table "sharded_session_recording_events" {
    override = true
    order_by     = ["team_id", "toHour(timestamp)", "session_id", "timestamp", "uuid"]
    partition_by = "toYYYYMMDD(timestamp)"
    ttl          = "toDate(created_at) + toIntervalWeek(3)"
    settings = {
      index_granularity = "512"
    }
    column "uuid" {
      type = "UUID"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "session_id" {
      type = "String"
    }
    column "window_id" {
      type = "String"
    }
    column "snapshot_data" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "has_full_snapshot" {
      type         = "Int8"
      materialized = "JSONExtractBool(snapshot_data, 'has_full_snapshot')"
      comment      = "column_materializer::has_full_snapshot"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "events_summary" {
      type         = "Array(String)"
      materialized = "JSONExtract(JSON_QUERY(snapshot_data, '$.events_summary[*]'), 'Array(String)')"
    }
    column "click_count" {
      type         = "Int8"
      materialized = "length(arrayFilter(x -> ((JSONExtractInt(x, 'type') = 3) AND (JSONExtractInt(x, 'data', 'source') = 2) AND (JSONExtractInt(x, 'data', 'source') = 2)), events_summary))"
    }
    column "keypress_count" {
      type         = "Int8"
      materialized = "length(arrayFilter(x -> ((JSONExtractInt(x, 'type') = 3) AND (JSONExtractInt(x, 'data', 'source') = 5)), events_summary))"
    }
    column "timestamps_summary" {
      type         = "Array(DateTime64(6, 'UTC'))"
      materialized = "arraySort(arrayMap(x -> toDateTime(JSONExtractInt(x, 'timestamp') / 1000), events_summary))"
    }
    column "first_event_timestamp" {
      type         = "DateTime64(6, 'UTC')"
      materialized = "arrayReduce('min', timestamps_summary)"
    }
    column "last_event_timestamp" {
      type         = "DateTime64(6, 'UTC')"
      materialized = "arrayReduce('max', timestamps_summary)"
    }
    column "urls" {
      type         = "Array(String)"
      materialized = "arrayFilter(x -> (x != ''), arrayMap(x -> JSONExtractString(x, 'data', 'href'), events_summary))"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.session_recording_events"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }

  table "swap_person_distinct_id" {
    override = true
    order_by = ["team_id", "distinct_id", "person_id"]
    settings = {
      index_granularity = "8192"
    }
    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    column "team_id" {
      type = "Int64"
    }
    column "_sign" {
      type    = "Int8"
      default = "1"
    }
    column "is_deleted" {
      type  = "Int8"
      alias = "if(_sign = -1, 1, 0)"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "replicated_collapsing_merge_tree" {
      zoo_path     = "/clickhouse/prod/tables/noshard/posthog.swap_person_distinct_id"
      replica_name = "{replica}-{shard}"
      sign_column  = "_sign"
    }
  }

  table "web_bounces_daily_distributed" {
    override = true
    column "period_bucket" {
      type = "DateTime"
    }
    column "team_id" {
      type = "UInt64"
    }
    column "host" {
      type = "String"
    }
    column "device_type" {
      type = "String"
    }
    column "updated_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "entry_pathname" {
      type = "String"
    }
    column "end_pathname" {
      type = "String"
    }
    column "browser" {
      type = "String"
    }
    column "os" {
      type = "String"
    }
    column "viewport_width" {
      type = "Int64"
    }
    column "viewport_height" {
      type = "Int64"
    }
    column "referring_domain" {
      type = "String"
    }
    column "utm_source" {
      type = "String"
    }
    column "utm_medium" {
      type = "String"
    }
    column "utm_campaign" {
      type = "String"
    }
    column "utm_term" {
      type = "String"
    }
    column "utm_content" {
      type = "String"
    }
    column "country_code" {
      type = "String"
    }
    column "city_name" {
      type = "String"
    }
    column "region_code" {
      type = "String"
    }
    column "region_name" {
      type = "String"
    }
    column "persons_uniq_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sessions_uniq_state" {
      type = "AggregateFunction(uniq, String)"
    }
    column "pageviews_count_state" {
      type = "AggregateFunction(sum, UInt64)"
    }
    column "bounces_count_state" {
      type = "AggregateFunction(sum, UInt64)"
    }
    column "total_session_duration_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "total_session_count_state" {
      type = "AggregateFunction(sum, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "web_bounces_daily"
      sharding_key    = "rand()"
    }
  }

  table "web_bounces_hourly_distributed" {
    override = true
    column "period_bucket" {
      type = "DateTime"
    }
    column "team_id" {
      type = "UInt64"
    }
    column "host" {
      type = "String"
    }
    column "device_type" {
      type = "String"
    }
    column "updated_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "entry_pathname" {
      type = "String"
    }
    column "end_pathname" {
      type = "String"
    }
    column "browser" {
      type = "String"
    }
    column "os" {
      type = "String"
    }
    column "viewport_width" {
      type = "Int64"
    }
    column "viewport_height" {
      type = "Int64"
    }
    column "referring_domain" {
      type = "String"
    }
    column "utm_source" {
      type = "String"
    }
    column "utm_medium" {
      type = "String"
    }
    column "utm_campaign" {
      type = "String"
    }
    column "utm_term" {
      type = "String"
    }
    column "utm_content" {
      type = "String"
    }
    column "country_code" {
      type = "String"
    }
    column "city_name" {
      type = "String"
    }
    column "region_code" {
      type = "String"
    }
    column "region_name" {
      type = "String"
    }
    column "persons_uniq_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sessions_uniq_state" {
      type = "AggregateFunction(uniq, String)"
    }
    column "pageviews_count_state" {
      type = "AggregateFunction(sum, UInt64)"
    }
    column "bounces_count_state" {
      type = "AggregateFunction(sum, UInt64)"
    }
    column "total_session_duration_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "total_session_count_state" {
      type = "AggregateFunction(sum, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "web_bounces_hourly"
      sharding_key    = "rand()"
    }
  }

  table "web_stats_daily_distributed" {
    override = true
    column "period_bucket" {
      type = "DateTime"
    }
    column "team_id" {
      type = "UInt64"
    }
    column "host" {
      type = "String"
    }
    column "device_type" {
      type = "String"
    }
    column "updated_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "pathname" {
      type = "String"
    }
    column "entry_pathname" {
      type = "String"
    }
    column "end_pathname" {
      type = "String"
    }
    column "browser" {
      type = "String"
    }
    column "os" {
      type = "String"
    }
    column "viewport_width" {
      type = "Int64"
    }
    column "viewport_height" {
      type = "Int64"
    }
    column "referring_domain" {
      type = "String"
    }
    column "utm_source" {
      type = "String"
    }
    column "utm_medium" {
      type = "String"
    }
    column "utm_campaign" {
      type = "String"
    }
    column "utm_term" {
      type = "String"
    }
    column "utm_content" {
      type = "String"
    }
    column "country_code" {
      type = "String"
    }
    column "city_name" {
      type = "String"
    }
    column "region_code" {
      type = "String"
    }
    column "region_name" {
      type = "String"
    }
    column "persons_uniq_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sessions_uniq_state" {
      type = "AggregateFunction(uniq, String)"
    }
    column "pageviews_count_state" {
      type = "AggregateFunction(sum, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "web_stats_daily"
      sharding_key    = "rand()"
    }
  }

  table "web_stats_hourly_distributed" {
    override = true
    column "period_bucket" {
      type = "DateTime"
    }
    column "team_id" {
      type = "UInt64"
    }
    column "host" {
      type = "String"
    }
    column "device_type" {
      type = "String"
    }
    column "updated_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "pathname" {
      type = "String"
    }
    column "entry_pathname" {
      type = "String"
    }
    column "end_pathname" {
      type = "String"
    }
    column "browser" {
      type = "String"
    }
    column "os" {
      type = "String"
    }
    column "viewport_width" {
      type = "Int64"
    }
    column "viewport_height" {
      type = "Int64"
    }
    column "referring_domain" {
      type = "String"
    }
    column "utm_source" {
      type = "String"
    }
    column "utm_medium" {
      type = "String"
    }
    column "utm_campaign" {
      type = "String"
    }
    column "utm_term" {
      type = "String"
    }
    column "utm_content" {
      type = "String"
    }
    column "country_code" {
      type = "String"
    }
    column "city_name" {
      type = "String"
    }
    column "region_code" {
      type = "String"
    }
    column "region_name" {
      type = "String"
    }
    column "persons_uniq_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sessions_uniq_state" {
      type = "AggregateFunction(uniq, String)"
    }
    column "pageviews_count_state" {
      type = "AggregateFunction(sum, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "web_stats_hourly"
      sharding_key    = "rand()"
    }
  }

  table "writable_events" {
    override = true
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "elements_chain" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "person_id" {
      type = "UUID"
    }
    column "person_created_at" {
      type = "DateTime64(3)"
    }
    column "person_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group0_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group1_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group2_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group3_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group4_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group0_created_at" {
      type = "DateTime64(3)"
    }
    column "group1_created_at" {
      type = "DateTime64(3)"
    }
    column "group2_created_at" {
      type = "DateTime64(3)"
    }
    column "group3_created_at" {
      type = "DateTime64(3)"
    }
    column "group4_created_at" {
      type = "DateTime64(3)"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
    column "dmat_string_0" {
      type = "Nullable(String)"
    }
    column "dmat_string_1" {
      type = "Nullable(String)"
    }
    column "dmat_string_2" {
      type = "Nullable(String)"
    }
    column "dmat_string_3" {
      type = "Nullable(String)"
    }
    column "dmat_string_4" {
      type = "Nullable(String)"
    }
    column "dmat_string_5" {
      type = "Nullable(String)"
    }
    column "dmat_string_6" {
      type = "Nullable(String)"
    }
    column "dmat_string_7" {
      type = "Nullable(String)"
    }
    column "dmat_string_8" {
      type = "Nullable(String)"
    }
    column "dmat_string_9" {
      type = "Nullable(String)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_events"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }

  table "writable_events_dead_letter_queue" {
    override = true
    column "id" {
      type = "UUID"
    }
    column "event_uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "String"
    }
    column "distinct_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "elements_chain" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "ip" {
      type = "String"
    }
    column "site_url" {
      type = "String"
    }
    column "now" {
      type = "DateTime64(6, 'UTC')"
    }
    column "raw_payload" {
      type = "String"
    }
    column "error_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "error_location" {
      type = "String"
    }
    column "error" {
      type = "String"
    }
    column "tags" {
      type = "Array(String)"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "events_dead_letter_queue"
    }
  }

  materialized_view "session_replay_features_mv" {
    # The ingestion nodes declare this name too, for the table they write through.
    # A data node holds a different object under it, so this restates rather than
    # redeclares.
    override = true
    to_table = "posthog.writable_session_replay_features"
    query    = <<SQL
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
  sum(click_count) AS click_count,
  sum(keypress_count) AS keypress_count,
  sum(mouse_activity_count) AS mouse_activity_count,
  sum(rage_click_count) AS rage_click_count,
  sum(dead_click_count) AS dead_click_count,
  sum(inter_action_gap_count) AS inter_action_gap_count,
  sum(inter_action_gap_sum_ms) AS inter_action_gap_sum_ms,
  sum(inter_action_gap_sum_of_squares_ms) AS inter_action_gap_sum_of_squares_ms,
  max(max_idle_gap_ms) AS max_idle_gap_ms,
  sum(quick_back_count) AS quick_back_count,
  sum(page_visit_count) AS page_visit_count,
  uniqExactArrayState(visited_urls) AS unique_url_count,
  sum(console_error_count) AS console_error_count,
  sum(console_error_after_click_count) AS console_error_after_click_count,
  sum(network_request_count) AS network_request_count,
  sum(network_failed_request_count) AS network_failed_request_count,
  sum(network_request_duration_sum) AS network_request_duration_sum,
  sum(network_request_duration_sum_of_squares) AS network_request_duration_sum_of_squares,
  sum(network_request_duration_count) AS network_request_duration_count,
  max(max_scroll_y) AS max_scroll_y,
  uniqExactArrayState(click_target_ids) AS unique_click_target_count,
  sum(text_selection_count) AS text_selection_count,
  max(is_deleted) AS is_deleted
FROM posthog.kafka_session_replay_features
GROUP BY
  session_id, team_id
SQL

    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "min_first_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "max_last_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "event_count" {
      type = "Int64"
    }
    column "mouse_position_count" {
      type = "Int64"
    }
    column "mouse_sum_x" {
      type = "Float64"
    }
    column "mouse_sum_x_squared" {
      type = "Float64"
    }
    column "mouse_sum_y" {
      type = "Float64"
    }
    column "mouse_sum_y_squared" {
      type = "Float64"
    }
    column "mouse_distance_traveled" {
      type = "Float64"
    }
    column "mouse_direction_change_count" {
      type = "Int64"
    }
    column "mouse_velocity_sum" {
      type = "Float64"
    }
    column "mouse_velocity_sum_of_squares" {
      type = "Float64"
    }
    column "mouse_velocity_count" {
      type = "Int64"
    }
    column "scroll_event_count" {
      type = "Int64"
    }
    column "total_scroll_magnitude" {
      type = "Float64"
    }
    column "scroll_direction_reversal_count" {
      type = "Int64"
    }
    column "rapid_scroll_reversal_count" {
      type = "Int64"
    }
    column "click_count" {
      type = "Int64"
    }
    column "keypress_count" {
      type = "Int64"
    }
    column "mouse_activity_count" {
      type = "Int64"
    }
    column "rage_click_count" {
      type = "Int64"
    }
    column "dead_click_count" {
      type = "Int64"
    }
    column "inter_action_gap_count" {
      type = "Int64"
    }
    column "inter_action_gap_sum_ms" {
      type = "Float64"
    }
    column "inter_action_gap_sum_of_squares_ms" {
      type = "Float64"
    }
    column "max_idle_gap_ms" {
      type = "Float64"
    }
    column "quick_back_count" {
      type = "Int64"
    }
    column "page_visit_count" {
      type = "Int64"
    }
    column "unique_url_count" {
      type = "AggregateFunction(uniqExactArray, Array(String))"
    }
    column "console_error_count" {
      type = "Int64"
    }
    column "console_error_after_click_count" {
      type = "Int64"
    }
    column "network_request_count" {
      type = "Int64"
    }
    column "network_failed_request_count" {
      type = "Int64"
    }
    column "network_request_duration_sum" {
      type = "Float64"
    }
    column "network_request_duration_sum_of_squares" {
      type = "Float64"
    }
    column "network_request_duration_count" {
      type = "Int64"
    }
    column "max_scroll_y" {
      type = "Float64"
    }
    column "unique_click_target_count" {
      type = "AggregateFunction(uniqExactArray, Array(Int64))"
    }
    column "text_selection_count" {
      type = "Int64"
    }
    column "is_deleted" {
      type = "UInt8"
    }
  }

  patch_table "events" {
    modify_column "properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "elements_chain" {
      type  = "String"
      after = "distinct_id"
    }
    column "person_id" {
      type  = "UUID"
      after = "created_at"
    }
    column "person_created_at" {
      type  = "DateTime64(3)"
      after = "person_id"
    }
    column "person_properties" {
      type  = "String"
      codec = "ZSTD(3)"
      after = "person_created_at"
    }
    column "group0_properties" {
      type  = "String"
      codec = "ZSTD(3)"
      after = "person_properties"
    }
    column "group1_properties" {
      type  = "String"
      codec = "ZSTD(3)"
      after = "group0_properties"
    }
    column "group2_properties" {
      type  = "String"
      codec = "ZSTD(3)"
      after = "group1_properties"
    }
    column "group3_properties" {
      type  = "String"
      codec = "ZSTD(3)"
      after = "group2_properties"
    }
    column "group4_properties" {
      type  = "String"
      codec = "ZSTD(3)"
      after = "group3_properties"
    }
    column "group0_created_at" {
      type  = "DateTime64(3)"
      after = "group4_properties"
    }
    column "group1_created_at" {
      type  = "DateTime64(3)"
      after = "group0_created_at"
    }
    column "group2_created_at" {
      type  = "DateTime64(3)"
      after = "group1_created_at"
    }
    column "group3_created_at" {
      type  = "DateTime64(3)"
      after = "group2_created_at"
    }
    column "group4_created_at" {
      type  = "DateTime64(3)"
      after = "group3_created_at"
    }
    column "_timestamp" {
      type  = "DateTime"
      after = "$session_id"
    }
    column "_offset" {
      type  = "UInt64"
      after = "_timestamp"
    }
    column "mat_metadata_backend" {
      type    = "String"
      comment = "column_materializer::properties::metadata.backend"
      after   = "person_mode"
    }
    column "mat_metadata_loggedIn" {
      type    = "String"
      comment = "column_materializer::properties::metadata.loggedIn"
      after   = "mat_metadata_backend"
    }
    column "mat_$ai_trace_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_trace_id"
      after   = "person_properties_map_custom"
    }
    column "mat_$ai_experiment_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_experiment_id"
      after   = "mat_$ai_prompt_name"
    }
  }

  patch_table "sharded_events" {
    column "elements_chain" {
      type  = "String"
      after = "distinct_id"
    }
    column "person_id" {
      type  = "UUID"
      after = "created_at"
    }
    column "person_created_at" {
      type  = "DateTime64(3)"
      after = "person_id"
    }
    column "person_properties" {
      type  = "String"
      codec = "ZSTD(3)"
      after = "person_created_at"
    }
    column "group0_properties" {
      type  = "String"
      codec = "ZSTD(3)"
      after = "person_properties"
    }
    column "group1_properties" {
      type  = "String"
      codec = "ZSTD(3)"
      after = "group0_properties"
    }
    column "group2_properties" {
      type  = "String"
      codec = "ZSTD(3)"
      after = "group1_properties"
    }
    column "group3_properties" {
      type  = "String"
      codec = "ZSTD(3)"
      after = "group2_properties"
    }
    column "group4_properties" {
      type  = "String"
      codec = "ZSTD(3)"
      after = "group3_properties"
    }
    column "group0_created_at" {
      type  = "DateTime64(3)"
      after = "group4_properties"
    }
    column "group1_created_at" {
      type  = "DateTime64(3)"
      after = "group0_created_at"
    }
    column "group2_created_at" {
      type  = "DateTime64(3)"
      after = "group1_created_at"
    }
    column "group3_created_at" {
      type  = "DateTime64(3)"
      after = "group2_created_at"
    }
    column "group4_created_at" {
      type  = "DateTime64(3)"
      after = "group3_created_at"
    }
    column "_timestamp" {
      type  = "DateTime"
      after = "$session_id"
    }
    column "_offset" {
      type  = "UInt64"
      after = "_timestamp"
    }
    column "mat_metadata_backend" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, 'metadata.backend'), '^\"|\"$', '')"
      after   = "person_mode"
    }
    column "mat_metadata_loggedIn" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, 'metadata.loggedIn'), '^\"|\"$', '')"
      after   = "mat_metadata_backend"
    }
    column "mat_$ai_trace_id" {
      type    = "Nullable(String)"
      default = "JSONExtract(properties, '$ai_trace_id', 'Nullable(String)')"
      after   = "person_properties_map_custom"
    }
    index "minmax_mat_metadata_backend" {
      expr        = "mat_metadata_backend"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_metadata_loggedIn" {
      expr        = "mat_metadata_loggedIn"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$ai_trace_id" {
      expr        = "`mat_$ai_trace_id`"
      type        = "minmax"
      granularity = 1
    }
    settings = {
      max_avg_part_size_for_too_many_parts = "0"
    }
  }

  patch_table "ai_events" {
    engine "distributed" {
      cluster_name    = "ai_events"
      remote_database = "posthog"
      remote_table    = "ai_events"
      sharding_key    = "rand()"
    }
  }

  patch_table "billing_usage_records" {
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_billing_usage_records"
      sharding_key    = "cityHash64(team_id)"
    }
  }

  patch_table "cohortpeople" {
    order_by     = ["team_id", "cohort_id", "person_id"]
    partition_by = "team_id % 16"
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.cohortpeople_new_partitioned"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  patch_table "ingestion_warnings" {
    modify_column "details" {
      type  = "String"
      codec = "ZSTD(3)"
    }
  }

  patch_table "plugin_log_entries" {
    order_by     = ["team_id", "plugin_id", "plugin_config_id", "timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.plugin_log_entries.fixed"
      replica_name   = "{replica}-{shard}"
      version_column = "_timestamp"
    }
  }

  patch_table "raw_sessions" {
    engine "distributed" {
      cluster_name    = "sessions"
      remote_database = "posthog"
      remote_table    = "raw_sessions"
      sharding_key    = "cityHash64(session_id_v7)"
    }
  }

  patch_table "raw_sessions_v3" {
    engine "distributed" {
      cluster_name    = "sessions"
      remote_database = "posthog"
      remote_table    = "raw_sessions_v3"
      sharding_key    = "cityHash64(session_id_v7)"
    }
  }

  patch_table "sessions" {
    engine "distributed" {
      cluster_name    = "sessions"
      remote_database = "posthog"
      remote_table    = "sessions"
      sharding_key    = "sipHash64(session_id)"
    }
  }

  patch_table "sharded_session_replay_events" {
    settings = {
      ttl_only_drop_parts = "1"
    }
    modify_column "snapshot_source" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
  }

  patch_table "writable_events_recent" {
    modify_column "group0_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    modify_column "group1_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    modify_column "group2_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    modify_column "group3_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    modify_column "group4_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    modify_column "person_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    modify_column "properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "historical_migration" {
      type  = "Bool"
      after = "person_mode"
    }
  }

  patch_table "writable_raw_sessions" {
    engine "distributed" {
      cluster_name    = "sessions"
      remote_database = "posthog"
      remote_table    = "raw_sessions"
      sharding_key    = "cityHash64(session_id_v7)"
    }
  }

  patch_table "writable_raw_sessions_v3" {
    column "hosts" {
      type  = "SimpleAggregateFunction(groupUniqArrayArray(100), Array(String))"
      after = "event_names"
    }
    column "emails" {
      type  = "SimpleAggregateFunction(groupUniqArrayArray(10), Array(String))"
      after = "hosts"
    }
    engine "distributed" {
      cluster_name    = "sessions"
      remote_database = "posthog"
      remote_table    = "raw_sessions_v3"
      sharding_key    = "cityHash64(session_id_v7)"
    }
  }

  patch_table "writable_session_replay_events" {
    drop_columns = ["is_deleted"]
  }

  patch_table "writable_sessions" {
    engine "distributed" {
      cluster_name    = "sessions"
      remote_database = "posthog"
      remote_table    = "sessions"
      sharding_key    = "sipHash64(session_id)"
    }
  }

  patch_view "events_batch_export" {
    query = <<SQL
SELECT
  team_id AS team_id,
  timestamp AS timestamp,
  event AS event,
  distinct_id AS distinct_id,
  toString(uuid) AS uuid,
  coalesce(inserted_at, _timestamp) AS _inserted_at,
  created_at AS created_at,
  elements_chain AS elements_chain,
  toString(person_id) AS person_id,
  nullIf(properties, '') AS properties,
  nullIf(person_properties, '') AS person_properties,
  nullIf(JSONExtractString(properties, '$set'), '') AS set,
  nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
FROM posthog.events
PREWHERE
  (coalesce(events.inserted_at, events._timestamp) >= {interval_start: DateTime64}) AND (coalesce(events.inserted_at, events._timestamp) < {interval_end: DateTime64})
WHERE
  (team_id = {team_id: Int64})
AND
  (events.timestamp >= ({interval_start: DateTime64} - toIntervalDay({lookback_days: Int32})))
AND
  (events.timestamp < ({interval_end: DateTime64} + toIntervalDay(1)))
AND
  ((length({include_events: Array(String)}) = 0) OR (event IN ({include_events: Array(String)})))
AND
  ((length({exclude_events: Array(String)}) = 0) OR (event NOT IN ({exclude_events: Array(String)})))
ORDER BY _inserted_at ASC, event ASC
LIMIT 1 BY team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid)
SETTINGS
  optimize_aggregation_in_order = 1
SQL

  }

  patch_view "events_batch_export_unbounded" {
    query = <<SQL
SELECT
  team_id AS team_id,
  timestamp AS timestamp,
  event AS event,
  distinct_id AS distinct_id,
  toString(uuid) AS uuid,
  coalesce(inserted_at, _timestamp) AS _inserted_at,
  created_at AS created_at,
  elements_chain AS elements_chain,
  toString(person_id) AS person_id,
  nullIf(properties, '') AS properties,
  nullIf(person_properties, '') AS person_properties,
  nullIf(JSONExtractString(properties, '$set'), '') AS set,
  nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
FROM posthog.events
PREWHERE
  (coalesce(events.inserted_at, events._timestamp) >= {interval_start: DateTime64}) AND (coalesce(events.inserted_at, events._timestamp) < {interval_end: DateTime64})
WHERE
  (team_id = {team_id: Int64})
AND
  ((length({include_events: Array(String)}) = 0) OR (event IN ({include_events: Array(String)})))
AND
  ((length({exclude_events: Array(String)}) = 0) OR (event NOT IN ({exclude_events: Array(String)})))
ORDER BY _inserted_at ASC, event ASC
LIMIT 1 BY team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid)
SETTINGS
  optimize_aggregation_in_order = 1
SQL

  }

  table "distributed_events_recent" {
    override = true
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "elements_chain" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "person_id" {
      type = "UUID"
    }
    column "person_created_at" {
      type = "DateTime64(3)"
    }
    column "person_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group0_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group1_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group2_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group3_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group4_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group0_created_at" {
      type = "DateTime64(3)"
    }
    column "group1_created_at" {
      type = "DateTime64(3)"
    }
    column "group2_created_at" {
      type = "DateTime64(3)"
    }
    column "group3_created_at" {
      type = "DateTime64(3)"
    }
    column "group4_created_at" {
      type = "DateTime64(3)"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_partition" {
      type = "UInt64"
    }
    column "inserted_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    column "_timestamp_ms" {
      type = "DateTime64(3)"
    }
    engine "distributed" {
      cluster_name    = "batch_exports"
      remote_database = "posthog"
      remote_table    = "sharded_events_recent"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }

  table "distributed_posthog_document_embeddings" {
    override = true
    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
      type = "LowCardinality(String)"
    }
    column "model_name" {
      type = "LowCardinality(String)"
    }
    column "rendering" {
      type = "LowCardinality(String)"
    }
    column "document_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(3, 'UTC')"
    }
    column "inserted_at" {
      type = "DateTime64(3, 'UTC')"
    }
    column "content" {
      type    = "String"
      default = "''"
    }
    column "embedding" {
      type = "Array(Float64)"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_partition" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_posthog_document_embeddings"
      sharding_key    = "cityHash64(document_id)"
    }
  }

  table "distributed_system_processes" {
    override = true
    settings = {
      skip_unavailable_shards = "1"
    }
    column "is_initial_query" {
      type = "UInt8"
    }
    column "user" {
      type = "String"
    }
    column "query_id" {
      type = "String"
    }
    column "address" {
      type = "IPv6"
    }
    column "port" {
      type = "UInt16"
    }
    column "initial_user" {
      type = "String"
    }
    column "initial_query_id" {
      type = "String"
    }
    column "initial_address" {
      type = "IPv6"
    }
    column "initial_port" {
      type = "UInt16"
    }
    column "interface" {
      type = "UInt8"
    }
    column "os_user" {
      type = "String"
    }
    column "client_hostname" {
      type = "String"
    }
    column "client_name" {
      type = "String"
    }
    column "client_revision" {
      type = "UInt64"
    }
    column "client_version_major" {
      type = "UInt64"
    }
    column "client_version_minor" {
      type = "UInt64"
    }
    column "client_version_patch" {
      type = "UInt64"
    }
    column "http_method" {
      type = "UInt8"
    }
    column "http_user_agent" {
      type = "String"
    }
    column "http_referer" {
      type = "String"
    }
    column "forwarded_for" {
      type = "String"
    }
    column "quota_key" {
      type = "String"
    }
    column "distributed_depth" {
      type = "UInt64"
    }
    column "elapsed" {
      type = "Float64"
    }
    column "is_cancelled" {
      type = "UInt8"
    }
    column "is_all_data_sent" {
      type = "UInt8"
    }
    column "read_rows" {
      type = "UInt64"
    }
    column "read_bytes" {
      type = "UInt64"
    }
    column "total_rows_approx" {
      type = "UInt64"
    }
    column "written_rows" {
      type = "UInt64"
    }
    column "written_bytes" {
      type = "UInt64"
    }
    column "memory_usage" {
      type = "Int64"
    }
    column "peak_memory_usage" {
      type = "Int64"
    }
    column "query" {
      type = "String"
    }
    column "query_kind" {
      type = "String"
    }
    column "thread_ids" {
      type = "Array(UInt64)"
    }
    column "ProfileEvents" {
      type = "Map(String, UInt64)"
    }
    column "Settings" {
      type = "Map(String, String)"
    }
    column "current_database" {
      type = "String"
    }
    column "ProfileEvents.Names" {
      type  = "Array(String)"
      alias = "mapKeys(ProfileEvents)"
    }
    column "ProfileEvents.Values" {
      type  = "Array(UInt64)"
      alias = "mapValues(ProfileEvents)"
    }
    column "Settings.Names" {
      type  = "Array(String)"
      alias = "mapKeys(Settings)"
    }
    column "Settings.Values" {
      type  = "Array(String)"
      alias = "mapValues(Settings)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "system"
      remote_table    = "processes"
    }
  }

  view "raw_sessions_v3_v" {
    override = true
    query = <<SQL
SELECT
  session_id_v7,
  session_timestamp,
  team_id,
  argMaxMerge(distinct_id) AS distinct_id,
  argMaxMerge(person_id) AS person_id,
  groupUniqArrayMerge(distinct_ids) AS distinct_ids,
  min(min_timestamp) AS min_timestamp,
  max(max_timestamp) AS max_timestamp,
  max(max_inserted_at) AS max_inserted_at,
  arrayDistinct(arrayFlatten(groupArray(urls))) AS urls,
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
  uniqUpToMerge(1)(page_screen_autocapture_uniq_up_to) AS page_screen_autocapture_uniq_up_to,
  groupUniqArrayMapMerge(flag_values) AS flag_values
FROM posthog.raw_sessions_v3
GROUP BY
  session_id_v7, session_timestamp, team_id
SQL

  }

  view "sessions_v" {
    override = true
    query = <<SQL
SELECT
  session_id,
  team_id,
  any(distinct_id) AS distinct_id,
  min(min_timestamp) AS min_timestamp,
  max(max_timestamp) AS max_timestamp,
  arrayDistinct(arrayFlatten(groupArray(urls))) AS urls,
  argMinMerge(entry_url) AS entry_url,
  argMaxMerge(exit_url) AS exit_url,
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
  sumMap(event_count_map) AS event_count_map,
  sum(pageview_count) AS pageview_count,
  sum(autocapture_count) AS autocapture_count
FROM posthog.sessions
GROUP BY
  session_id, team_id
SQL

  }

  patch_table "tophog" {
    engine "distributed" {
      cluster_name    = "ops"
      remote_database = "posthog"
      remote_table    = "sharded_tophog"
      sharding_key    = "cityHash64(toString(key))"
    }
  }

}

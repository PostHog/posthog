database "posthog" {
  table "raw_sessions" {
    override = true
    order_by     = ["team_id", "toStartOfHour(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000)))", "cityHash64(session_id_v7)", "session_id_v7"]
    partition_by = "toYYYYMM(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000)))"
    sample_by    = "cityHash64(session_id_v7)"
    settings = {
      index_granularity = "8192"
    }
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
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/sessions/noshard/posthog.raw_sessions"
      replica_name = "{shard}-{replica}"
    }
  }
  table "sessions" {
    override = true
    order_by     = ["toStartOfDay(min_timestamp)", "team_id", "session_id"]
    partition_by = "toYYYYMM(min_timestamp)"
    settings = {
      index_granularity = "512"
    }
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "SimpleAggregateFunction(any, String)"
    }
    column "min_timestamp" {
      type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "urls" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "entry_url" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "exit_url" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
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
    column "event_count_map" {
      type = "SimpleAggregateFunction(sumMap, Map(String, Int64))"
    }
    column "pageview_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "autocapture_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/sessions/noshard/posthog.sessions"
      replica_name = "{shard}-{replica}"
    }
  }

  # The sessions nodes read events through the same Distributed proxy the data
  # node carries, so the column core is the shared abstract.
  table "events" {
    extend = "_event_base"
    patch_column "$group_0" {
      comment = "column_materializer::$group_0"
    }
    patch_column "$group_1" {
      comment = "column_materializer::$group_1"
    }
    patch_column "$group_2" {
      comment = "column_materializer::$group_2"
    }
    patch_column "$group_3" {
      comment = "column_materializer::$group_3"
    }
    patch_column "$group_4" {
      comment = "column_materializer::$group_4"
    }
    patch_column "$window_id" {
      comment = "column_materializer::$window_id"
    }
    patch_column "$session_id" {
      comment = "column_materializer::$session_id"
    }
    patch_column "elements_chain_href" {
      comment = "column_materializer::elements_chain::href"
    }
    patch_column "elements_chain_texts" {
      comment = "column_materializer::elements_chain::texts"
    }
    patch_column "elements_chain_ids" {
      comment = "column_materializer::elements_chain::ids"
    }
    patch_column "elements_chain_elements" {
      comment = "column_materializer::elements_chain::elements"
    }
    patch_column "mat_historical_migration" {
      comment = "column_materializer::properties::historical_migration"
    }
    patch_column "mat_$ai_session_id" {
      comment = "column_materializer::properties::$ai_session_id"
    }
    patch_column "mat_$ai_is_error" {
      comment = "column_materializer::properties::$ai_is_error"
    }
    patch_column "mat_$ai_prompt_name" {
      comment = "column_materializer::properties::$ai_prompt_name"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_events"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }

  # The materialized-column tail these nodes carry, positioned to match the live
  # physical order. It arrives as a patch because `after` only positions a
  # patch_table add: inside a declaration, declaration order is the order.
  patch_table "events" {
    column "elements_hash" {
      type  = "String"
      after = "distinct_id"
    }
    column "_timestamp" {
      type  = "DateTime"
      after = "created_at"
    }
    column "_offset" {
      type  = "UInt64"
      after = "_timestamp"
    }
    column "elements_chain" {
      type  = "String"
      after = "_offset"
    }
    column "mat_$user_id" {
      type    = "String"
      comment = "column_materializer::$user_id"
      after   = "elements_chain"
    }
    column "mat_$browser" {
      type    = "String"
      comment = "column_materializer::$browser"
      after   = "mat_$user_id"
    }
    column "mat_$host" {
      type    = "String"
      comment = "column_materializer::$host"
      after   = "mat_$browser"
    }
    column "mat_$current_url" {
      type    = "String"
      comment = "column_materializer::$current_url"
      after   = "mat_$host"
    }
    column "mat_distinct_id" {
      type    = "String"
      comment = "column_materializer::distinct_id"
      after   = "mat_$current_url"
    }
    column "mat_action" {
      type    = "String"
      comment = "column_materializer::action"
      after   = "mat_distinct_id"
    }
    column "mat_origin" {
      type    = "String"
      comment = "column_materializer::origin"
      after   = "mat_action"
    }
    column "mat_email" {
      type    = "String"
      comment = "column_materializer::email"
      after   = "mat_origin"
    }
    column "mat_key" {
      type    = "String"
      comment = "column_materializer::key"
      after   = "mat_email"
    }
    column "mat_insight" {
      type    = "String"
      comment = "column_materializer::insight"
      after   = "mat_key"
    }
    column "mat_$event_type" {
      type    = "String"
      comment = "column_materializer::$event_type"
      after   = "mat_insight"
    }
    column "mat_created_by" {
      type    = "String"
      comment = "column_materializer::created_by"
      after   = "mat_$event_type"
    }
    column "mat_total_event_actions_count" {
      type    = "String"
      comment = "column_materializer::total_event_actions_count"
      after   = "mat_created_by"
    }
    column "mat_is_demo_project" {
      type    = "String"
      comment = "column_materializer::is_demo_project"
      after   = "mat_total_event_actions_count"
    }
    column "mat_$active_feature_flags" {
      type    = "String"
      comment = "column_materializer::$active_feature_flags"
      after   = "mat_is_demo_project"
    }
    column "mat_filters_count" {
      type    = "String"
      comment = "column_materializer::filters_count"
      after   = "mat_$active_feature_flags"
    }
    column "mat_utm_source" {
      type    = "String"
      comment = "column_materializer::utm_source"
      after   = "mat_filters_count"
    }
    column "mat_apiErrorMessage" {
      type    = "String"
      comment = "column_materializer::apiErrorMessage"
      after   = "mat_utm_source"
    }
    column "mat_$referring_domain" {
      type    = "String"
      comment = "column_materializer::$referring_domain"
      after   = "mat_apiErrorMessage"
    }
    column "mat_statusCode" {
      type    = "String"
      comment = "column_materializer::statusCode"
      after   = "mat_$referring_domain"
    }
    column "mat_deal_id" {
      type    = "String"
      comment = "column_materializer::deal_id"
      after   = "mat_statusCode"
    }
    column "mat_realm" {
      type    = "String"
      comment = "column_materializer::realm"
      after   = "mat_deal_id"
    }
    column "mat_$lib" {
      type    = "String"
      comment = "column_materializer::$lib"
      after   = "$group_4"
    }
    column "mat_$os" {
      type    = "String"
      comment = "column_materializer::$os"
      after   = "mat_$lib"
    }
    column "mat_$initial_referrer" {
      type    = "String"
      comment = "column_materializer::$initial_referrer"
      after   = "mat_$os"
    }
    column "mat_$app_version" {
      type    = "String"
      comment = "column_materializer::$app_version"
      after   = "mat_$initial_referrer"
    }
    column "mat_$initial_referring_domain" {
      type    = "String"
      comment = "column_materializer::$initial_referring_domain"
      after   = "mat_$app_version"
    }
    column "mat_symbol" {
      type    = "String"
      comment = "column_materializer::symbol"
      after   = "mat_$initial_referring_domain"
    }
    column "mat_page" {
      type    = "String"
      comment = "column_materializer::page"
      after   = "mat_symbol"
    }
    column "mat_type" {
      type    = "String"
      comment = "column_materializer::type"
      after   = "mat_page"
    }
    column "mat_currentScreen" {
      type    = "String"
      comment = "column_materializer::currentScreen"
      after   = "mat_type"
    }
    column "mat_utm_campaign" {
      type    = "String"
      comment = "column_materializer::utm_campaign"
      after   = "mat_currentScreen"
    }
    column "mat_is_organization_first_user" {
      type    = "String"
      comment = "column_materializer::is_organization_first_user"
      after   = "mat_utm_campaign"
    }
    column "mat_is_first_component_load" {
      type    = "String"
      comment = "column_materializer::is_first_component_load"
      after   = "mat_is_organization_first_user"
    }
    column "mat_team" {
      type    = "String"
      comment = "column_materializer::team"
      after   = "mat_is_first_component_load"
    }
    column "mat_context" {
      type    = "String"
      comment = "column_materializer::context"
      after   = "mat_team"
    }
    column "mat_sdk" {
      type    = "String"
      comment = "column_materializer::sdk"
      after   = "mat_context"
    }
    column "mat_created_by_system" {
      type    = "String"
      comment = "column_materializer::created_by_system"
      after   = "mat_sdk"
    }
    column "mat_item_count" {
      type    = "String"
      comment = "column_materializer::item_count"
      after   = "mat_created_by_system"
    }
    column "mat_$ip" {
      type    = "String"
      comment = "column_materializer::$ip"
      after   = "mat_item_count"
    }
    column "mat_$referrer" {
      type    = "String"
      comment = "column_materializer::$referrer"
      after   = "mat_$ip"
    }
    column "mat_action_name" {
      type    = "String"
      comment = "column_materializer::action_name"
      after   = "mat_$referrer"
    }
    column "mat_$geoip_country_name" {
      type    = "String"
      comment = "column_materializer::$geoip_country_name"
      after   = "mat_action_name"
    }
    column "mat_$device_model" {
      type    = "String"
      comment = "column_materializer::$device_model"
      after   = "mat_$geoip_country_name"
    }
    column "mat_progress" {
      type    = "String"
      comment = "column_materializer::progress"
      after   = "mat_$device_model"
    }
    column "mat_chain" {
      type    = "String"
      comment = "column_materializer::chain"
      after   = "mat_progress"
    }
    column "mat_$device_type" {
      type    = "String"
      comment = "column_materializer::$device_type"
      after   = "mat_chain"
    }
    column "mat_usd" {
      type    = "String"
      comment = "column_materializer::usd"
      after   = "mat_$device_type"
    }
    column "mat_app_name" {
      type    = "String"
      comment = "column_materializer::app_name"
      after   = "mat_usd"
    }
    column "mat_$screen_name" {
      type    = "String"
      comment = "column_materializer::$screen_name"
      after   = "mat_app_name"
    }
    column "mat_index" {
      type    = "String"
      comment = "column_materializer::index"
      after   = "mat_$screen_name"
    }
    column "mat_token" {
      type    = "String"
      comment = "column_materializer::token"
      after   = "mat_index"
    }
    column "mat_method" {
      type    = "String"
      comment = "column_materializer::method"
      after   = "mat_token"
    }
    column "mat_address" {
      type    = "String"
      comment = "column_materializer::address"
      after   = "mat_method"
    }
    column "mat_name" {
      type    = "String"
      comment = "column_materializer::name"
      after   = "mat_address"
    }
    column "mat_inviteCode" {
      type    = "String"
      comment = "column_materializer::inviteCode"
      after   = "mat_name"
    }
    column "mat_osName" {
      type    = "String"
      comment = "column_materializer::osName"
      after   = "$session_id"
    }
    column "mat_nativeBuildVersion" {
      type    = "String"
      comment = "column_materializer::nativeBuildVersion"
      after   = "mat_osName"
    }
    column "mat_revenue" {
      type    = "String"
      comment = "column_materializer::revenue"
      after   = "mat_nativeBuildVersion"
    }
    column "group_0" {
      type  = "String"
      alias = "`$group_0`"
      after = "mat_revenue"
    }
    column "group_1" {
      type  = "String"
      alias = "`$group_1`"
      after = "group_0"
    }
    column "group_2" {
      type  = "String"
      alias = "`$group_2`"
      after = "group_1"
    }
    column "group_3" {
      type  = "String"
      alias = "`$group_3`"
      after = "group_2"
    }
    column "group_4" {
      type  = "String"
      alias = "`$group_4`"
      after = "group_3"
    }
    column "alias_mat__user_id" {
      type  = "String"
      alias = "`mat_$user_id`"
      after = "group_4"
    }
    column "alias_mat__browser" {
      type  = "String"
      alias = "`mat_$browser`"
      after = "alias_mat__user_id"
    }
    column "alias_mat__host" {
      type  = "String"
      alias = "`mat_$host`"
      after = "alias_mat__browser"
    }
    column "alias_mat__current_url" {
      type  = "String"
      alias = "`mat_$current_url`"
      after = "alias_mat__host"
    }
    column "alias_mat__event_type" {
      type  = "String"
      alias = "`mat_$event_type`"
      after = "alias_mat__current_url"
    }
    column "alias_mat__active_feature_flags" {
      type  = "String"
      alias = "`mat_$active_feature_flags`"
      after = "alias_mat__event_type"
    }
    column "alias_mat__referring_domain" {
      type  = "String"
      alias = "`mat_$referring_domain`"
      after = "alias_mat__active_feature_flags"
    }
    column "alias_mat__lib" {
      type  = "String"
      alias = "`mat_$lib`"
      after = "alias_mat__referring_domain"
    }
    column "alias_mat__os" {
      type  = "String"
      alias = "`mat_$os`"
      after = "alias_mat__lib"
    }
    column "alias_mat__initial_referrer" {
      type  = "String"
      alias = "`mat_$initial_referrer`"
      after = "alias_mat__os"
    }
    column "alias_mat__app_version" {
      type  = "String"
      alias = "`mat_$app_version`"
      after = "alias_mat__initial_referrer"
    }
    column "alias_mat__initial_referring_domain" {
      type  = "String"
      alias = "`mat_$initial_referring_domain`"
      after = "alias_mat__app_version"
    }
    column "alias_mat__ip" {
      type  = "String"
      alias = "`mat_$ip`"
      after = "alias_mat__initial_referring_domain"
    }
    column "alias_mat__referrer" {
      type  = "String"
      alias = "`mat_$referrer`"
      after = "alias_mat__ip"
    }
    column "alias_mat__geoip_country_name" {
      type  = "String"
      alias = "`mat_$geoip_country_name`"
      after = "alias_mat__referrer"
    }
    column "alias_mat__device_model" {
      type  = "String"
      alias = "`mat_$device_model`"
      after = "alias_mat__geoip_country_name"
    }
    column "alias_mat__device_type" {
      type  = "String"
      alias = "`mat_$device_type`"
      after = "alias_mat__device_model"
    }
    column "alias_mat__screen_name" {
      type  = "String"
      alias = "`mat_$screen_name`"
      after = "alias_mat__device_type"
    }
    column "person_id" {
      type  = "UUID"
      after = "alias_mat__screen_name"
    }
    column "person_properties" {
      type  = "String"
      after = "person_id"
    }
    column "group0_properties" {
      type  = "String"
      after = "person_properties"
    }
    column "group1_properties" {
      type  = "String"
      after = "group0_properties"
    }
    column "group2_properties" {
      type  = "String"
      after = "group1_properties"
    }
    column "group3_properties" {
      type  = "String"
      after = "group2_properties"
    }
    column "group4_properties" {
      type  = "String"
      after = "group3_properties"
    }
    column "person_created_at" {
      type  = "DateTime64(3)"
      after = "group4_properties"
    }
    column "group0_created_at" {
      type  = "DateTime64(3)"
      after = "person_created_at"
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
    column "mat_arguments" {
      type    = "String"
      comment = "column_materializer::properties::arguments"
      after   = "group4_created_at"
    }
    column "mat_source" {
      type    = "String"
      comment = "column_materializer::properties::source"
      after   = "mat_arguments"
    }
    column "mat_pp_email" {
      type    = "String"
      comment = "column_materializer::person_properties::email"
      after   = "mat_source"
    }
    column "mat_$time" {
      type    = "String"
      comment = "column_materializer::properties::$time"
      after   = "mat_pp_email"
    }
    column "mat_$pathname" {
      type    = "String"
      comment = "column_materializer::properties::$pathname"
      after   = "mat_$time"
    }
    column "mat_$geoip_city_name" {
      type    = "String"
      comment = "column_materializer::properties::$geoip_city_name"
      after   = "mat_$pathname"
    }
    column "mat_community_id" {
      type    = "String"
      comment = "column_materializer::properties::community_id"
      after   = "mat_$geoip_city_name"
    }
    column "mat_thread_id" {
      type    = "String"
      comment = "column_materializer::properties::thread_id"
      after   = "mat_community_id"
    }
    column "mat_Event_productCode" {
      type    = "String"
      comment = "column_materializer::properties::Event.productCode"
      after   = "mat_thread_id"
    }
    column "mat_env" {
      type    = "String"
      comment = "column_materializer::properties::env"
      after   = "mat_Event_productCode"
    }
    column "mat_target" {
      type    = "String"
      comment = "column_materializer::properties::target"
      after   = "mat_env"
    }
    column "mat_Subscription_plan_amount" {
      type    = "String"
      comment = "column_materializer::properties::Subscription.plan.amount"
      after   = "mat_target"
    }
    column "mat_title" {
      type    = "String"
      comment = "column_materializer::properties::title"
      after   = "mat_Subscription_plan_amount"
    }
    column "mat_Connection_app_name" {
      type    = "String"
      comment = "column_materializer::properties::Connection.app.name"
      after   = "mat_title"
    }
    column "mat_utm_medium" {
      type    = "String"
      comment = "column_materializer::properties::utm_medium"
      after   = "mat_Connection_app_name"
    }
    column "mat_Account_client_id" {
      type    = "String"
      comment = "column_materializer::properties::Account.client_id"
      after   = "mat_utm_medium"
    }
    column "mat_HTTP_Method" {
      type    = "String"
      comment = "column_materializer::properties::HTTP Method"
      after   = "mat_Account_client_id"
    }
    column "mat_audio_duration" {
      type    = "String"
      comment = "column_materializer::properties::audio_duration"
      after   = "mat_HTTP_Method"
    }
    column "mat_duration" {
      type    = "String"
      comment = "column_materializer::properties::duration"
      after   = "mat_audio_duration"
    }
    column "mat_url" {
      type    = "String"
      comment = "column_materializer::properties::url"
      after   = "mat_duration"
    }
    column "mat_group_id" {
      type    = "String"
      comment = "column_materializer::properties::group_id"
      after   = "mat_url"
    }
    column "mat_platform" {
      type    = "String"
      comment = "column_materializer::properties::platform"
      after   = "mat_group_id"
    }
    column "mat_pp_$browser" {
      type    = "String"
      comment = "column_materializer::person_properties::$browser"
      after   = "mat_platform"
    }
    column "mat_payment_status" {
      type    = "String"
      comment = "column_materializer::properties::payment_status"
      after   = "mat_pp_$browser"
    }
    column "mat_testSessionId" {
      type    = "String"
      comment = "column_materializer::properties::testSessionId"
      after   = "mat_payment_status"
    }
    column "mat_$sent_at" {
      type    = "String"
      comment = "column_materializer::properties::$sent_at"
      after   = "inserted_at"
    }
    column "mat_pp_companyName" {
      type    = "String"
      comment = "column_materializer::person_properties::companyName"
      after   = "mat_$sent_at"
    }
    column "mat_function" {
      type    = "String"
      comment = "column_materializer::properties::function"
      after   = "mat_pp_companyName"
    }
    column "mat_store_url" {
      type    = "String"
      comment = "column_materializer::properties::store_url"
      after   = "mat_function"
    }
    column "mat_email_domain" {
      type    = "String"
      comment = "column_materializer::properties::email_domain"
      after   = "mat_store_url"
    }
    column "mat_institution_name" {
      type    = "String"
      comment = "column_materializer::properties::institution_name"
      after   = "mat_email_domain"
    }
    column "mat_authentication_method" {
      type    = "String"
      comment = "column_materializer::properties::authentication_method"
      after   = "mat_institution_name"
    }
    column "mat_initial_step" {
      type    = "String"
      comment = "column_materializer::properties::initial_step"
      after   = "mat_authentication_method"
    }
    column "mat_status_message" {
      type    = "String"
      comment = "column_materializer::properties::status_message"
      after   = "mat_initial_step"
    }
    column "mat_mode" {
      type    = "String"
      comment = "column_materializer::properties::mode"
      after   = "mat_status_message"
    }
    column "mat_protocol" {
      type    = "String"
      comment = "column_materializer::properties::protocol"
      after   = "mat_mode"
    }
    column "mat_job_type" {
      type    = "String"
      comment = "column_materializer::properties::job_type"
      after   = "mat_protocol"
    }
    column "mat_is_oauth" {
      type    = "String"
      comment = "column_materializer::properties::is_oauth"
      after   = "mat_job_type"
    }
    column "mat_is_initial_aggregation" {
      type    = "String"
      comment = "column_materializer::properties::is_initial_aggregation"
      after   = "mat_is_oauth"
    }
    column "mat_search_term" {
      type    = "String"
      comment = "column_materializer::properties::search_term"
      after   = "mat_is_initial_aggregation"
    }
    column "mat_valid_ach_accounts" {
      type    = "String"
      comment = "column_materializer::properties::valid_ach_accounts"
      after   = "mat_search_term"
    }
    column "mat_gross" {
      type    = "String"
      comment = "column_materializer::properties::gross"
      after   = "mat_valid_ach_accounts"
    }
    column "mat_orderType" {
      type    = "String"
      comment = "column_materializer::properties::orderType"
      after   = "mat_gross"
    }
    column "mat_sku" {
      type    = "String"
      comment = "column_materializer::properties::sku"
      after   = "mat_orderType"
    }
    column "mat_dual_channel" {
      type    = "String"
      comment = "column_materializer::properties::dual_channel"
      after   = "mat_sku"
    }
    column "mat_channel" {
      type    = "String"
      comment = "column_materializer::properties::channel"
      after   = "mat_dual_channel"
    }
    column "mat_workspaceId" {
      type    = "String"
      comment = "column_materializer::properties::workspaceId"
      after   = "mat_channel"
    }
    column "mat_numberOfSecrets" {
      type    = "String"
      comment = "column_materializer::properties::numberOfSecrets"
      after   = "mat_workspaceId"
    }
    column "mat_organizations" {
      type    = "String"
      comment = "column_materializer::properties::organizations"
      after   = "mat_numberOfSecrets"
    }
    column "mat_organization" {
      type    = "String"
      comment = "column_materializer::properties::organization"
      after   = "mat_organizations"
    }
    column "mat_contributionError" {
      type    = "String"
      comment = "column_materializer::properties::contributionError"
      after   = "mat_organization"
    }
    column "mat_phone" {
      type    = "String"
      comment = "column_materializer::properties::phone"
      after   = "mat_contributionError"
    }
    column "mat_$initial_pathname" {
      type    = "String"
      comment = "column_materializer::properties::$initial_pathname"
      after   = "mat_phone"
    }
    column "mat_organization_name" {
      type    = "String"
      comment = "column_materializer::properties::organization_name"
      after   = "mat_$initial_pathname"
    }
    column "mat_category" {
      type    = "String"
      comment = "column_materializer::properties::category"
      after   = "mat_organization_name"
    }
    column "mat_$lib_version" {
      type    = "String"
      comment = "column_materializer::properties::$lib_version"
      after   = "mat_category"
    }
    column "mat_pp_$initial_utm_campaign" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_utm_campaign"
      after   = "mat_$lib_version"
    }
    column "mat_pp_$initial_utm_medium" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_utm_medium"
      after   = "mat_pp_$initial_utm_campaign"
    }
    column "mat_pp_$initial_gclid" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_gclid"
      after   = "mat_pp_$initial_utm_medium"
    }
    column "mat_pp_$initial_gad_source" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_gad_source"
      after   = "mat_pp_$initial_gclid"
    }
    column "mat_pp_$initial_utm_source" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_utm_source"
      after   = "mat_pp_$initial_gad_source"
    }
    column "mat_pp_$initial_referring_domain" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_referring_domain"
      after   = "mat_pp_$initial_utm_source"
    }
    column "mat_pp_$initial_utm_term" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_utm_term"
      after   = "mat_pp_$initial_referring_domain"
    }
    column "mat_pp_$initial_utm_content" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_utm_content"
      after   = "mat_pp_$initial_utm_term"
    }
    column "mat_pp_$initial_gbraid" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_gbraid::disabled"
      after   = "mat_pp_$initial_utm_content"
    }
    column "mat_pp_$initial_wbraid" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_wbraid::disabled"
      after   = "mat_pp_$initial_gbraid"
    }
    column "mat_pp_$initial_msclkid" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_msclkid"
      after   = "mat_pp_$initial_wbraid"
    }
    column "mat_pp_$initial_fbclid" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_fbclid"
      after   = "mat_pp_$initial_msclkid"
    }
    column "mat_$geoip_subdivision_1_code" {
      type    = "String"
      comment = "column_materializer::properties::$geoip_subdivision_1_code"
      after   = "mat_pp_$initial_fbclid"
    }
    column "mat_wlo_enabled" {
      type    = "String"
      comment = "column_materializer::properties::wlo_enabled"
      after   = "mat_$geoip_subdivision_1_code"
    }
    column "mat_$prev_pageview_max_scroll_percentage" {
      type    = "String"
      comment = "column_materializer::properties::$prev_pageview_max_scroll_percentage"
      after   = "mat_wlo_enabled"
    }
    column "mat_$prev_pageview_max_content_percentage" {
      type    = "String"
      comment = "column_materializer::properties::$prev_pageview_max_content_percentage"
      after   = "mat_$prev_pageview_max_scroll_percentage"
    }
    column "mat_$prev_pageview_pathname" {
      type    = "String"
      comment = "column_materializer::properties::$prev_pageview_pathname"
      after   = "mat_$prev_pageview_max_content_percentage"
    }
    column "mat_pp_$initial_pathname" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_pathname"
      after   = "mat_$prev_pageview_pathname"
    }
    column "mat_pp_$geoip_country_code" {
      type    = "String"
      comment = "column_materializer::person_properties::$geoip_country_code"
      after   = "mat_pp_$initial_pathname"
    }
    column "mat_pp_username" {
      type    = "String"
      comment = "column_materializer::person_properties::username"
      after   = "mat_pp_$geoip_country_code"
    }
    column "mat_pp_serverMasterclass" {
      type    = "String"
      comment = "column_materializer::person_properties::serverMasterclass"
      after   = "mat_pp_username"
    }
    column "mat_content_length" {
      type    = "String"
      comment = "column_materializer::properties::content_length"
      after   = "mat_pp_serverMasterclass"
    }
    column "mat_pp_serverMarketing" {
      type    = "String"
      comment = "column_materializer::person_properties::serverMarketing"
      after   = "mat_content_length"
    }
    column "mat_$browser_version" {
      type    = "String"
      comment = "column_materializer::properties::$browser_version"
      after   = "mat_pp_serverMarketing"
    }
    column "mat_pp_role" {
      type    = "String"
      comment = "column_materializer::person_properties::role"
      after   = "mat_$browser_version"
    }
    column "mat_pp_customer" {
      type    = "String"
      comment = "column_materializer::person_properties::customer"
      after   = "mat_pp_role"
    }
    column "mat_event" {
      type    = "String"
      comment = "column_materializer::properties::event"
      after   = "mat_pp_customer"
    }
    column "mat_disable_institution_search" {
      type    = "String"
      comment = "column_materializer::properties::disable_institution_search"
      after   = "mat_event"
    }
    column "mat_is_first_event_for_user" {
      type    = "String"
      comment = "column_materializer::properties::is_first_event_for_user"
      after   = "mat_disable_institution_search"
    }
    column "mat_current_member_guid" {
      type    = "String"
      comment = "column_materializer::properties::current_member_guid"
      after   = "mat_is_first_event_for_user"
    }
    column "mat_user_agent" {
      type    = "String"
      comment = "column_materializer::properties::user_agent"
      after   = "mat_current_member_guid"
    }
    column "mat_is_test_user" {
      type    = "String"
      comment = "column_materializer::properties::is_test_user"
      after   = "mat_user_agent"
    }
    column "mat_referrer" {
      type    = "String"
      comment = "column_materializer::properties::referrer"
      after   = "mat_is_test_user"
    }
    column "mat_pp_$initial_current_url" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_current_url"
      after   = "mat_referrer"
    }
    column "mat_most_recent_app_os" {
      type    = "String"
      comment = "column_materializer::properties::most_recent_app_os"
      after   = "mat_pp_$initial_current_url"
    }
    column "mat_pp_hubspot_score" {
      type    = "String"
      comment = "column_materializer::person_properties::hubspot_score"
      after   = "mat_most_recent_app_os"
    }
    column "mat_pp_id" {
      type    = "String"
      comment = "column_materializer::person_properties::id"
      after   = "mat_pp_hubspot_score"
    }
    column "mat_pp_$current_url" {
      type    = "String"
      comment = "column_materializer::person_properties::$current_url"
      after   = "mat_pp_id"
    }
    column "mat_product_key" {
      type    = "String"
      comment = "column_materializer::properties::product_key"
      after   = "mat_pp_$current_url"
    }
    column "mat_Plan_type_and_filter" {
      type    = "String"
      comment = "column_materializer::properties::Plan type and filter"
      after   = "mat_product_key"
    }
    column "mat_$app_namespace" {
      type    = "String"
      comment = "column_materializer::properties::$app_namespace"
      after   = "mat_Plan_type_and_filter"
    }
    column "mat_$os_name" {
      type    = "String"
      comment = "column_materializer::properties::$os_name"
      after   = "mat_$app_namespace"
    }
    column "mat_pp_$os_name" {
      type    = "String"
      comment = "column_materializer::person_properties::$os_name::disabled"
      after   = "mat_$os_name"
    }
    column "mat_pp_$app_version" {
      type    = "String"
      comment = "column_materializer::person_properties::$app_version"
      after   = "mat_pp_$os_name"
    }
    column "mat_subscriptionStatus" {
      type    = "String"
      comment = "column_materializer::properties::subscriptionStatus"
      after   = "mat_pp_$app_version"
    }
    column "mat_$screen_height" {
      type    = "String"
      comment = "column_materializer::properties::$screen_height"
      after   = "mat_subscriptionStatus"
    }
    column "mat_$screen_width" {
      type    = "String"
      comment = "column_materializer::properties::$screen_width"
      after   = "mat_$screen_height"
    }
    column "mat_tag" {
      type    = "String"
      comment = "column_materializer::properties::tag"
      after   = "mat_$screen_width"
    }
    column "mat_$app_build" {
      type    = "String"
      comment = "column_materializer::properties::$app_build"
      after   = "mat_tag"
    }
    column "mat_surface_tag" {
      type    = "String"
      comment = "column_materializer::properties::surface_tag"
      after   = "mat_$app_build"
    }
    column "mat_survey_responses_count_in_period" {
      type    = "String"
      comment = "column_materializer::properties::survey_responses_count_in_period"
      after   = "mat_surface_tag"
    }
    column "mat_event_count_in_month" {
      type    = "String"
      comment = "column_materializer::properties::event_count_in_month"
      after   = "mat_survey_responses_count_in_period"
    }
    column "mat_ramp" {
      type    = "String"
      comment = "column_materializer::properties::ramp"
      after   = "mat_event_count_in_month"
    }
    column "mat_auto_chapters" {
      type    = "String"
      comment = "column_materializer::properties::auto_chapters"
      after   = "mat_ramp"
    }
    column "mat_sentiment_analysis" {
      type    = "String"
      comment = "column_materializer::properties::sentiment_analysis"
      after   = "mat_auto_chapters"
    }
    column "mat_redact_pii" {
      type    = "String"
      comment = "column_materializer::properties::redact_pii"
      after   = "mat_sentiment_analysis"
    }
    column "mat_content_safety" {
      type    = "String"
      comment = "column_materializer::properties::content_safety"
      after   = "mat_redact_pii"
    }
    column "mat_iab_categories" {
      type    = "String"
      comment = "column_materializer::properties::iab_categories"
      after   = "mat_content_safety"
    }
    column "mat_auto_highlights" {
      type    = "String"
      comment = "column_materializer::properties::auto_highlights"
      after   = "mat_iab_categories"
    }
    column "mat_entity_detection" {
      type    = "String"
      comment = "column_materializer::properties::entity_detection"
      after   = "mat_auto_highlights"
    }
    column "mat_summarization" {
      type    = "String"
      comment = "column_materializer::properties::summarization"
      after   = "mat_entity_detection"
    }
    column "mat_pp_val_region" {
      type    = "String"
      comment = "column_materializer::person_properties::val_region"
      after   = "mat_summarization"
    }
    column "mat_client_id" {
      type    = "String"
      comment = "column_materializer::properties::client_id"
      after   = "mat_pp_val_region"
    }
    column "mat_$geoip_country_code" {
      type    = "String"
      comment = "column_materializer::properties::$geoip_country_code"
      after   = "mat_client_id"
    }
    column "mat_disfluencies" {
      type    = "String"
      comment = "column_materializer::properties::disfluencies"
      after   = "mat_$geoip_country_code"
    }
    column "mat_filter_profanity" {
      type    = "String"
      comment = "column_materializer::properties::filter_profanity"
      after   = "mat_disfluencies"
    }
    column "mat_speaker_labels" {
      type    = "String"
      comment = "column_materializer::properties::speaker_labels"
      after   = "mat_filter_profanity"
    }
    column "mat_language_detection" {
      type    = "String"
      comment = "column_materializer::properties::language_detection"
      after   = "mat_speaker_labels"
    }
    column "mat_product_analytics_projected_amount" {
      type    = "String"
      comment = "column_materializer::properties::product_analytics_projected_amount"
      after   = "mat_language_detection"
    }
    column "mat_recordings_projected_amount" {
      type    = "String"
      comment = "column_materializer::properties::recordings_projected_amount"
      after   = "mat_product_analytics_projected_amount"
    }
    column "mat_events_projected_amount" {
      type    = "String"
      comment = "column_materializer::properties::events_projected_amount"
      after   = "mat_recordings_projected_amount"
    }
    column "mat_session_replay_projected_amount" {
      type    = "String"
      comment = "column_materializer::properties::session_replay_projected_amount"
      after   = "mat_events_projected_amount"
    }
    column "mat_total_usd" {
      type    = "String"
      comment = "column_materializer::properties::total_usd"
      after   = "mat_session_replay_projected_amount"
    }
    column "mat_stripe_amount_paid" {
      type    = "String"
      comment = "column_materializer::properties::stripe_amount_paid"
      after   = "mat_total_usd"
    }
    column "mat_workspace" {
      type    = "String"
      comment = "column_materializer::properties::workspace"
      after   = "mat_stripe_amount_paid"
    }
    column "mat_created_at" {
      type    = "String"
      comment = "column_materializer::properties::created_at"
      after   = "mat_workspace"
    }
    column "mat_kind" {
      type    = "String"
      comment = "column_materializer::properties::kind"
      after   = "mat_created_at"
    }
    column "mat_product" {
      type    = "String"
      comment = "column_materializer::properties::product"
      after   = "mat_kind"
    }
    column "mat_message" {
      type    = "String"
      comment = "column_materializer::properties::message"
      after   = "mat_product"
    }
    column "mat_initiator" {
      type    = "String"
      comment = "column_materializer::properties::initiator"
      after   = "mat_message"
    }
    column "mat_query" {
      type    = "String"
      comment = "column_materializer::properties::query"
      after   = "mat_initiator"
    }
    column "mat_$survey_id" {
      type    = "String"
      comment = "column_materializer::properties::$survey_id"
      after   = "mat_query"
    }
    column "mat_$survey_response_1" {
      type    = "String"
      comment = "column_materializer::properties::$survey_response_1"
      after   = "mat_$survey_id"
    }
    column "mat_ticketId" {
      type    = "String"
      comment = "column_materializer::properties::ticketId"
      after   = "mat_$survey_response_1"
    }
    column "mat_$survey_response" {
      type    = "String"
      comment = "column_materializer::properties::$survey_response"
      after   = "mat_ticketId"
    }
    column "mat_conceptName" {
      type    = "String"
      comment = "column_materializer::properties::conceptName"
      after   = "mat_$survey_response"
    }
    column "mat_apiName" {
      type    = "String"
      comment = "column_materializer::properties::apiName"
      after   = "mat_conceptName"
    }
    column "mat_workplace_billing_plan" {
      type    = "String"
      comment = "column_materializer::properties::workplace_billing_plan"
      after   = "mat_apiName"
    }
    column "mat_$el_text" {
      type    = "String"
      comment = "column_materializer::properties::$el_text"
      after   = "mat_workplace_billing_plan"
    }
    column "mat_recording_count_in_period" {
      type    = "String"
      comment = "column_materializer::properties::recording_count_in_period"
      after   = "mat_$el_text"
    }
    column "mat_$os_version" {
      type    = "String"
      comment = "column_materializer::properties::$os_version"
      after   = "mat_recording_count_in_period"
    }
    column "mat_orderId" {
      type    = "String"
      comment = "column_materializer::properties::orderId"
      after   = "mat_$os_version"
    }
    column "mat_commit_sha" {
      type    = "String"
      comment = "column_materializer::properties::commit_sha"
      after   = "mat_orderId"
    }
    column "mat_$feature_flag_payloads" {
      type    = "String"
      comment = "column_materializer::properties::$feature_flag_payloads"
      after   = "mat_commit_sha"
    }
    column "mat_event_count_in_period" {
      type    = "String"
      comment = "column_materializer::properties::event_count_in_period"
      after   = "mat_$feature_flag_payloads"
    }
    column "mat_$groups" {
      type    = "String"
      comment = "column_materializer::properties::$groups"
      after   = "mat_event_count_in_period"
    }
    column "mat_$feature_flag" {
      type    = "String"
      comment = "column_materializer::properties::$feature_flag"
      after   = "mat_$groups"
    }
    column "mat_utm_content" {
      type    = "String"
      comment = "column_materializer::properties::utm_content"
      after   = "mat_$feature_flag"
    }
    column "mat_gclid" {
      type    = "String"
      comment = "column_materializer::properties::gclid"
      after   = "mat_utm_content"
    }
    column "mat_gad_source" {
      type    = "String"
      comment = "column_materializer::properties::gad_source"
      after   = "mat_gclid"
    }
    column "mat_gbraid" {
      type    = "String"
      comment = "column_materializer::properties::gbraid"
      after   = "mat_gad_source"
    }
    column "mat_wbraid" {
      type    = "String"
      comment = "column_materializer::properties::wbraid"
      after   = "mat_gbraid"
    }
    column "mat_fbclid" {
      type    = "String"
      comment = "column_materializer::properties::fbclid"
      after   = "mat_wbraid"
    }
    column "mat_msclkid" {
      type    = "String"
      comment = "column_materializer::properties::msclkid"
      after   = "mat_fbclid"
    }
    column "mat_organization_id" {
      type    = "String"
      comment = "column_materializer::properties::organization_id"
      after   = "mat_msclkid"
    }
    column "mat_owner_type" {
      type    = "String"
      comment = "column_materializer::properties::owner_type"
      after   = "mat_organization_id"
    }
    column "mat_device_type" {
      type    = "String"
      comment = "column_materializer::properties::device_type"
      after   = "mat_owner_type"
    }
    column "mat_$device_id" {
      type    = "String"
      comment = "column_materializer::properties::$device_id"
      after   = "mat_device_type"
    }
    column "mat_pp_$geoip_continent_name" {
      type    = "String"
      comment = "column_materializer::person_properties::$geoip_continent_name"
      after   = "mat_$device_id"
    }
    column "mat_$feature_flag_response" {
      type    = "String"
      comment = "column_materializer::properties::$feature_flag_response"
      after   = "mat_pp_$geoip_continent_name"
    }
    column "mat_pp_utm_source" {
      type    = "String"
      comment = "column_materializer::person_properties::utm_source"
      after   = "mat_$feature_flag_response"
    }
    column "mat_pp_$referring_domain" {
      type    = "String"
      comment = "column_materializer::person_properties::$referring_domain"
      after   = "mat_pp_utm_source"
    }
    column "mat_pp_Email_Domain" {
      type    = "String"
      comment = "column_materializer::person_properties::Email Domain"
      after   = "mat_pp_$referring_domain"
    }
    column "mat_machine_id" {
      type    = "String"
      comment = "column_materializer::properties::machine_id"
      after   = "mat_pp_Email_Domain"
    }
    column "mat_user_email_domain" {
      type    = "String"
      comment = "column_materializer::properties::user_email_domain"
      after   = "mat_machine_id"
    }
    column "mat_$lib_version__minor" {
      type    = "String"
      comment = "column_materializer::properties::$lib_version__minor"
      after   = "mat_user_email_domain"
    }
    column "mat_region" {
      type    = "String"
      comment = "column_materializer::properties::region"
      after   = "mat_$lib_version__minor"
    }
    column "mat_pp_user_email_domain" {
      type    = "String"
      comment = "column_materializer::person_properties::user_email_domain"
      after   = "mat_region"
    }
    column "mat_url_promotion_id" {
      type    = "String"
      comment = "column_materializer::properties::url_promotion_id"
      after   = "mat_pp_user_email_domain"
    }
    column "mat_$lib_custom_api_host" {
      type    = "String"
      comment = "column_materializer::properties::$lib_custom_api_host"
      after   = "mat_url_promotion_id"
    }
    column "mat_user_platform" {
      type    = "String"
      comment = "column_materializer::properties::user_platform"
      after   = "person_mode"
    }
    column "mat_pp_$geoip_country_name" {
      type    = "String"
      comment = "column_materializer::person_properties::$geoip_country_name"
      after   = "mat_user_platform"
    }
    column "mat_environment" {
      type    = "String"
      comment = "column_materializer::properties::environment"
      after   = "mat_pp_$geoip_country_name"
    }
    column "mat_customer_email" {
      type    = "String"
      comment = "column_materializer::properties::customer_email"
      after   = "mat_environment"
    }
    column "mat_client_name" {
      type    = "String"
      comment = "column_materializer::properties::client_name"
      after   = "mat_customer_email"
    }
    column "mat_screen_name" {
      type    = "String"
      comment = "column_materializer::properties::screen_name"
      after   = "mat_client_name"
    }
    column "mat_app_version" {
      type    = "String"
      comment = "column_materializer::properties::app_version"
      after   = "mat_screen_name"
    }
    column "mat_subdomain" {
      type    = "String"
      comment = "column_materializer::properties::subdomain"
      after   = "is_deleted"
    }
    column "mat_$device" {
      type    = "String"
      comment = "column_materializer::properties::$device"
      after   = "mat_subdomain"
    }
    column "mat_id" {
      type    = "String"
      comment = "column_materializer::properties::id"
      after   = "mat_$device"
    }
    column "mat_record_id" {
      type    = "String"
      comment = "column_materializer::properties::record_id"
      after   = "mat_id"
    }
    column "mat_referrer_id" {
      type    = "String"
      comment = "column_materializer::properties::record_id"
      after   = "mat_record_id"
    }
    column "mat_$exception_issue_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$exception_issue_id"
      after   = "mat_referrer_id"
    }
    column "mat_$exception_fingerprint" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$exception_fingerprint"
      after   = "mat_$exception_issue_id"
    }
    column "mat_$web_vitals_LCP_value" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$web_vitals_LCP_value"
      after   = "mat_$exception_fingerprint"
    }
    column "mat_$web_vitals_FCP_value" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$web_vitals_FCP_value"
      after   = "mat_$web_vitals_LCP_value"
    }
    column "mat_$web_vitals_CLS_value" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$web_vitals_CLS_value"
      after   = "mat_$web_vitals_FCP_value"
    }
    column "mat_$web_vitals_INP_value" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$web_vitals_INP_value"
      after   = "mat_$web_vitals_CLS_value"
    }
    column "mat_$viewport_width" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$viewport_width"
      after   = "mat_$web_vitals_INP_value"
    }
    column "mat_$viewport_height" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$viewport_height"
      after   = "mat_$viewport_width"
    }
    column "mat_$anon_distinct_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$anon_distinct_id"
      after   = "mat_$viewport_height"
    }
    column "mat_$ai_trace_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_trace_id"
      after   = "person_properties_map_custom"
    }
    column "mat_$ai_model" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_model"
      after   = "mat_$ai_trace_id"
    }
    column "mat_$ai_provider" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_provider"
      after   = "mat_$ai_model"
    }
    column "mat_$ai_parent_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_parent_id"
      after   = "mat_$ai_provider"
    }
    column "mat_$ai_span_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_span_id"
      after   = "mat_$ai_parent_id"
    }
    column "mat_$ai_http_status" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_http_status"
      after   = "mat_$ai_span_id"
    }
    column "mat_$exception_types" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$exception_types"
      after   = "mat_$ai_http_status"
    }
    column "mat_$exception_values" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$exception_values"
      after   = "mat_$exception_types"
    }
    column "mat_$exception_sources" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$exception_sources"
      after   = "mat_$exception_values"
    }
    column "mat_$exception_functions" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$exception_functions"
      after   = "mat_$exception_sources"
    }
    column "mat_$process_person_profile" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$process_person_profile"
      after   = "$session_id_uuid"
    }
    column "mat_$is_identified" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$is_identified"
      after   = "properties_group_ai"
    }
    column "dmat_numeric_0" {
      type  = "Nullable(Float64)"
      after = "dmat_string_9"
    }
    column "dmat_numeric_1" {
      type  = "Nullable(Float64)"
      after = "dmat_numeric_0"
    }
    column "dmat_numeric_2" {
      type  = "Nullable(Float64)"
      after = "dmat_numeric_1"
    }
    column "dmat_numeric_3" {
      type  = "Nullable(Float64)"
      after = "dmat_numeric_2"
    }
    column "dmat_numeric_4" {
      type  = "Nullable(Float64)"
      after = "dmat_numeric_3"
    }
    column "dmat_numeric_5" {
      type  = "Nullable(Float64)"
      after = "dmat_numeric_4"
    }
    column "dmat_numeric_6" {
      type  = "Nullable(Float64)"
      after = "dmat_numeric_5"
    }
    column "dmat_numeric_7" {
      type  = "Nullable(Float64)"
      after = "dmat_numeric_6"
    }
    column "dmat_numeric_8" {
      type  = "Nullable(Float64)"
      after = "dmat_numeric_7"
    }
    column "dmat_numeric_9" {
      type  = "Nullable(Float64)"
      after = "dmat_numeric_8"
    }
    column "dmat_bool_0" {
      type  = "Nullable(UInt8)"
      after = "dmat_numeric_9"
    }
    column "dmat_bool_1" {
      type  = "Nullable(UInt8)"
      after = "dmat_bool_0"
    }
    column "dmat_bool_2" {
      type  = "Nullable(UInt8)"
      after = "dmat_bool_1"
    }
    column "dmat_bool_3" {
      type  = "Nullable(UInt8)"
      after = "dmat_bool_2"
    }
    column "dmat_bool_4" {
      type  = "Nullable(UInt8)"
      after = "dmat_bool_3"
    }
    column "dmat_bool_5" {
      type  = "Nullable(UInt8)"
      after = "dmat_bool_4"
    }
    column "dmat_bool_6" {
      type  = "Nullable(UInt8)"
      after = "dmat_bool_5"
    }
    column "dmat_bool_7" {
      type  = "Nullable(UInt8)"
      after = "dmat_bool_6"
    }
    column "dmat_bool_8" {
      type  = "Nullable(UInt8)"
      after = "dmat_bool_7"
    }
    column "dmat_bool_9" {
      type  = "Nullable(UInt8)"
      after = "dmat_bool_8"
    }
    column "dmat_datetime_0" {
      type  = "Nullable(DateTime64(6, 'UTC'))"
      after = "dmat_bool_9"
    }
    column "dmat_datetime_1" {
      type  = "Nullable(DateTime64(6, 'UTC'))"
      after = "dmat_datetime_0"
    }
    column "dmat_datetime_2" {
      type  = "Nullable(DateTime64(6, 'UTC'))"
      after = "dmat_datetime_1"
    }
    column "dmat_datetime_3" {
      type  = "Nullable(DateTime64(6, 'UTC'))"
      after = "dmat_datetime_2"
    }
    column "dmat_datetime_4" {
      type  = "Nullable(DateTime64(6, 'UTC'))"
      after = "dmat_datetime_3"
    }
    column "dmat_datetime_5" {
      type  = "Nullable(DateTime64(6, 'UTC'))"
      after = "dmat_datetime_4"
    }
    column "dmat_datetime_6" {
      type  = "Nullable(DateTime64(6, 'UTC'))"
      after = "dmat_datetime_5"
    }
    column "dmat_datetime_7" {
      type  = "Nullable(DateTime64(6, 'UTC'))"
      after = "dmat_datetime_6"
    }
    column "dmat_datetime_8" {
      type  = "Nullable(DateTime64(6, 'UTC'))"
      after = "dmat_datetime_7"
    }
    column "dmat_datetime_9" {
      type  = "Nullable(DateTime64(6, 'UTC'))"
      after = "dmat_datetime_8"
    }
    column "mat_$ai_total_cost_usd" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_total_cost_usd"
      after   = "historical_migration"
    }
    column "properties_group_ai_large" {
      type  = "Map(String, String)"
      after = "mat_$ai_total_cost_usd"
    }
  }
}

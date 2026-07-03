database "posthog" {
  table "channel_definition" {
    column "domain" {
      type = "String"
    }
    column "kind" {
      type = "String"
    }
    column "domain_type" {
      type = "Nullable(String)"
    }
    column "type_if_paid" {
      type = "Nullable(String)"
    }
    column "type_if_organic" {
      type = "Nullable(String)"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "channel_definition"
    }
  }
  table "events" {
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "String"
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
    column "elements_hash" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "elements_chain" {
      type = "String"
    }
    column "mat_$user_id" {
      type    = "String"
      comment = "column_materializer::$user_id"
    }
    column "mat_$browser" {
      type    = "String"
      comment = "column_materializer::$browser"
    }
    column "mat_$host" {
      type    = "String"
      comment = "column_materializer::$host"
    }
    column "mat_$current_url" {
      type    = "String"
      comment = "column_materializer::$current_url"
    }
    column "mat_distinct_id" {
      type    = "String"
      comment = "column_materializer::distinct_id"
    }
    column "mat_action" {
      type    = "String"
      comment = "column_materializer::action"
    }
    column "mat_origin" {
      type    = "String"
      comment = "column_materializer::origin"
    }
    column "mat_email" {
      type    = "String"
      comment = "column_materializer::email"
    }
    column "mat_key" {
      type    = "String"
      comment = "column_materializer::key"
    }
    column "mat_insight" {
      type    = "String"
      comment = "column_materializer::insight"
    }
    column "mat_$event_type" {
      type    = "String"
      comment = "column_materializer::$event_type"
    }
    column "mat_created_by" {
      type    = "String"
      comment = "column_materializer::created_by"
    }
    column "mat_total_event_actions_count" {
      type    = "String"
      comment = "column_materializer::total_event_actions_count"
    }
    column "mat_is_demo_project" {
      type    = "String"
      comment = "column_materializer::is_demo_project"
    }
    column "mat_$active_feature_flags" {
      type    = "String"
      comment = "column_materializer::$active_feature_flags"
    }
    column "mat_filters_count" {
      type    = "String"
      comment = "column_materializer::filters_count"
    }
    column "mat_utm_source" {
      type    = "String"
      comment = "column_materializer::utm_source"
    }
    column "mat_apiErrorMessage" {
      type    = "String"
      comment = "column_materializer::apiErrorMessage"
    }
    column "mat_$referring_domain" {
      type    = "String"
      comment = "column_materializer::$referring_domain"
    }
    column "mat_statusCode" {
      type    = "String"
      comment = "column_materializer::statusCode"
    }
    column "mat_deal_id" {
      type    = "String"
      comment = "column_materializer::deal_id"
    }
    column "mat_realm" {
      type    = "String"
      comment = "column_materializer::realm"
    }
    column "$group_0" {
      type    = "String"
      comment = "column_materializer::$group_0"
    }
    column "$group_1" {
      type    = "String"
      comment = "column_materializer::$group_1"
    }
    column "$group_2" {
      type    = "String"
      comment = "column_materializer::$group_2"
    }
    column "$group_3" {
      type    = "String"
      comment = "column_materializer::$group_3"
    }
    column "$group_4" {
      type    = "String"
      comment = "column_materializer::$group_4"
    }
    column "mat_$lib" {
      type    = "String"
      comment = "column_materializer::$lib"
    }
    column "mat_$os" {
      type    = "String"
      comment = "column_materializer::$os"
    }
    column "mat_$initial_referrer" {
      type    = "String"
      comment = "column_materializer::$initial_referrer"
    }
    column "mat_$app_version" {
      type    = "String"
      comment = "column_materializer::$app_version"
    }
    column "mat_$initial_referring_domain" {
      type    = "String"
      comment = "column_materializer::$initial_referring_domain"
    }
    column "mat_symbol" {
      type    = "String"
      comment = "column_materializer::symbol"
    }
    column "mat_page" {
      type    = "String"
      comment = "column_materializer::page"
    }
    column "mat_type" {
      type    = "String"
      comment = "column_materializer::type"
    }
    column "mat_currentScreen" {
      type    = "String"
      comment = "column_materializer::currentScreen"
    }
    column "mat_utm_campaign" {
      type    = "String"
      comment = "column_materializer::utm_campaign"
    }
    column "mat_is_organization_first_user" {
      type    = "String"
      comment = "column_materializer::is_organization_first_user"
    }
    column "mat_is_first_component_load" {
      type    = "String"
      comment = "column_materializer::is_first_component_load"
    }
    column "mat_team" {
      type    = "String"
      comment = "column_materializer::team"
    }
    column "mat_context" {
      type    = "String"
      comment = "column_materializer::context"
    }
    column "mat_sdk" {
      type    = "String"
      comment = "column_materializer::sdk"
    }
    column "mat_created_by_system" {
      type    = "String"
      comment = "column_materializer::created_by_system"
    }
    column "mat_item_count" {
      type    = "String"
      comment = "column_materializer::item_count"
    }
    column "mat_$ip" {
      type    = "String"
      comment = "column_materializer::$ip"
    }
    column "mat_$referrer" {
      type    = "String"
      comment = "column_materializer::$referrer"
    }
    column "mat_action_name" {
      type    = "String"
      comment = "column_materializer::action_name"
    }
    column "mat_$geoip_country_name" {
      type    = "String"
      comment = "column_materializer::$geoip_country_name"
    }
    column "mat_$device_model" {
      type    = "String"
      comment = "column_materializer::$device_model"
    }
    column "mat_progress" {
      type    = "String"
      comment = "column_materializer::progress"
    }
    column "mat_chain" {
      type    = "String"
      comment = "column_materializer::chain"
    }
    column "mat_$device_type" {
      type    = "String"
      comment = "column_materializer::$device_type"
    }
    column "mat_usd" {
      type    = "String"
      comment = "column_materializer::usd"
    }
    column "mat_app_name" {
      type    = "String"
      comment = "column_materializer::app_name"
    }
    column "mat_$screen_name" {
      type    = "String"
      comment = "column_materializer::$screen_name"
    }
    column "mat_index" {
      type    = "String"
      comment = "column_materializer::index"
    }
    column "mat_token" {
      type    = "String"
      comment = "column_materializer::token"
    }
    column "mat_method" {
      type    = "String"
      comment = "column_materializer::method"
    }
    column "mat_address" {
      type    = "String"
      comment = "column_materializer::address"
    }
    column "mat_name" {
      type    = "String"
      comment = "column_materializer::name"
    }
    column "mat_inviteCode" {
      type    = "String"
      comment = "column_materializer::inviteCode"
    }
    column "$window_id" {
      type    = "String"
      comment = "column_materializer::$window_id"
    }
    column "$session_id" {
      type    = "String"
      comment = "column_materializer::$session_id"
    }
    column "mat_osName" {
      type    = "String"
      comment = "column_materializer::osName"
    }
    column "mat_nativeBuildVersion" {
      type    = "String"
      comment = "column_materializer::nativeBuildVersion"
    }
    column "mat_revenue" {
      type    = "String"
      comment = "column_materializer::revenue"
    }
    column "group_0" {
      type  = "String"
      alias = "`$group_0`"
    }
    column "group_1" {
      type  = "String"
      alias = "`$group_1`"
    }
    column "group_2" {
      type  = "String"
      alias = "`$group_2`"
    }
    column "group_3" {
      type  = "String"
      alias = "`$group_3`"
    }
    column "group_4" {
      type  = "String"
      alias = "`$group_4`"
    }
    column "alias_mat__user_id" {
      type  = "String"
      alias = "`mat_$user_id`"
    }
    column "alias_mat__browser" {
      type  = "String"
      alias = "`mat_$browser`"
    }
    column "alias_mat__host" {
      type  = "String"
      alias = "`mat_$host`"
    }
    column "alias_mat__current_url" {
      type  = "String"
      alias = "`mat_$current_url`"
    }
    column "alias_mat__event_type" {
      type  = "String"
      alias = "`mat_$event_type`"
    }
    column "alias_mat__active_feature_flags" {
      type  = "String"
      alias = "`mat_$active_feature_flags`"
    }
    column "alias_mat__referring_domain" {
      type  = "String"
      alias = "`mat_$referring_domain`"
    }
    column "alias_mat__lib" {
      type  = "String"
      alias = "`mat_$lib`"
    }
    column "alias_mat__os" {
      type  = "String"
      alias = "`mat_$os`"
    }
    column "alias_mat__initial_referrer" {
      type  = "String"
      alias = "`mat_$initial_referrer`"
    }
    column "alias_mat__app_version" {
      type  = "String"
      alias = "`mat_$app_version`"
    }
    column "alias_mat__initial_referring_domain" {
      type  = "String"
      alias = "`mat_$initial_referring_domain`"
    }
    column "alias_mat__ip" {
      type  = "String"
      alias = "`mat_$ip`"
    }
    column "alias_mat__referrer" {
      type  = "String"
      alias = "`mat_$referrer`"
    }
    column "alias_mat__geoip_country_name" {
      type  = "String"
      alias = "`mat_$geoip_country_name`"
    }
    column "alias_mat__device_model" {
      type  = "String"
      alias = "`mat_$device_model`"
    }
    column "alias_mat__device_type" {
      type  = "String"
      alias = "`mat_$device_type`"
    }
    column "alias_mat__screen_name" {
      type  = "String"
      alias = "`mat_$screen_name`"
    }
    column "person_id" {
      type = "UUID"
    }
    column "person_properties" {
      type = "String"
    }
    column "group0_properties" {
      type = "String"
    }
    column "group1_properties" {
      type = "String"
    }
    column "group2_properties" {
      type = "String"
    }
    column "group3_properties" {
      type = "String"
    }
    column "group4_properties" {
      type = "String"
    }
    column "person_created_at" {
      type = "DateTime64(3)"
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
    column "mat_arguments" {
      type    = "String"
      comment = "column_materializer::properties::arguments"
    }
    column "mat_source" {
      type    = "String"
      comment = "column_materializer::properties::source"
    }
    column "mat_pp_email" {
      type    = "String"
      comment = "column_materializer::person_properties::email"
    }
    column "mat_$time" {
      type    = "String"
      comment = "column_materializer::properties::$time"
    }
    column "mat_$pathname" {
      type    = "String"
      comment = "column_materializer::properties::$pathname"
    }
    column "mat_$geoip_city_name" {
      type    = "String"
      comment = "column_materializer::properties::$geoip_city_name"
    }
    column "mat_community_id" {
      type    = "String"
      comment = "column_materializer::properties::community_id"
    }
    column "mat_thread_id" {
      type    = "String"
      comment = "column_materializer::properties::thread_id"
    }
    column "mat_Event_productCode" {
      type    = "String"
      comment = "column_materializer::properties::Event.productCode"
    }
    column "mat_env" {
      type    = "String"
      comment = "column_materializer::properties::env"
    }
    column "mat_target" {
      type    = "String"
      comment = "column_materializer::properties::target"
    }
    column "mat_Subscription_plan_amount" {
      type    = "String"
      comment = "column_materializer::properties::Subscription.plan.amount"
    }
    column "mat_title" {
      type    = "String"
      comment = "column_materializer::properties::title"
    }
    column "mat_Connection_app_name" {
      type    = "String"
      comment = "column_materializer::properties::Connection.app.name"
    }
    column "mat_utm_medium" {
      type    = "String"
      comment = "column_materializer::properties::utm_medium"
    }
    column "mat_Account_client_id" {
      type    = "String"
      comment = "column_materializer::properties::Account.client_id"
    }
    column "mat_HTTP_Method" {
      type    = "String"
      comment = "column_materializer::properties::HTTP Method"
    }
    column "mat_audio_duration" {
      type    = "String"
      comment = "column_materializer::properties::audio_duration"
    }
    column "mat_duration" {
      type    = "String"
      comment = "column_materializer::properties::duration"
    }
    column "mat_url" {
      type    = "String"
      comment = "column_materializer::properties::url"
    }
    column "mat_group_id" {
      type    = "String"
      comment = "column_materializer::properties::group_id"
    }
    column "mat_platform" {
      type    = "String"
      comment = "column_materializer::properties::platform"
    }
    column "mat_pp_$browser" {
      type    = "String"
      comment = "column_materializer::person_properties::$browser"
    }
    column "mat_payment_status" {
      type    = "String"
      comment = "column_materializer::properties::payment_status"
    }
    column "mat_testSessionId" {
      type    = "String"
      comment = "column_materializer::properties::testSessionId"
    }
    column "inserted_at" {
      type    = "Nullable(DateTime64(6, 'UTC'))"
      default = "now64()"
    }
    column "mat_$sent_at" {
      type    = "String"
      comment = "column_materializer::properties::$sent_at"
    }
    column "mat_pp_companyName" {
      type    = "String"
      comment = "column_materializer::person_properties::companyName"
    }
    column "mat_function" {
      type    = "String"
      comment = "column_materializer::properties::function"
    }
    column "mat_store_url" {
      type    = "String"
      comment = "column_materializer::properties::store_url"
    }
    column "mat_email_domain" {
      type    = "String"
      comment = "column_materializer::properties::email_domain"
    }
    column "mat_institution_name" {
      type    = "String"
      comment = "column_materializer::properties::institution_name"
    }
    column "mat_authentication_method" {
      type    = "String"
      comment = "column_materializer::properties::authentication_method"
    }
    column "mat_initial_step" {
      type    = "String"
      comment = "column_materializer::properties::initial_step"
    }
    column "mat_status_message" {
      type    = "String"
      comment = "column_materializer::properties::status_message"
    }
    column "mat_mode" {
      type    = "String"
      comment = "column_materializer::properties::mode"
    }
    column "mat_protocol" {
      type    = "String"
      comment = "column_materializer::properties::protocol"
    }
    column "mat_job_type" {
      type    = "String"
      comment = "column_materializer::properties::job_type"
    }
    column "mat_is_oauth" {
      type    = "String"
      comment = "column_materializer::properties::is_oauth"
    }
    column "mat_is_initial_aggregation" {
      type    = "String"
      comment = "column_materializer::properties::is_initial_aggregation"
    }
    column "mat_search_term" {
      type    = "String"
      comment = "column_materializer::properties::search_term"
    }
    column "mat_valid_ach_accounts" {
      type    = "String"
      comment = "column_materializer::properties::valid_ach_accounts"
    }
    column "mat_gross" {
      type    = "String"
      comment = "column_materializer::properties::gross"
    }
    column "mat_orderType" {
      type    = "String"
      comment = "column_materializer::properties::orderType"
    }
    column "mat_sku" {
      type    = "String"
      comment = "column_materializer::properties::sku"
    }
    column "mat_dual_channel" {
      type    = "String"
      comment = "column_materializer::properties::dual_channel"
    }
    column "mat_channel" {
      type    = "String"
      comment = "column_materializer::properties::channel"
    }
    column "mat_workspaceId" {
      type    = "String"
      comment = "column_materializer::properties::workspaceId"
    }
    column "mat_numberOfSecrets" {
      type    = "String"
      comment = "column_materializer::properties::numberOfSecrets"
    }
    column "mat_organizations" {
      type    = "String"
      comment = "column_materializer::properties::organizations"
    }
    column "mat_organization" {
      type    = "String"
      comment = "column_materializer::properties::organization"
    }
    column "mat_contributionError" {
      type    = "String"
      comment = "column_materializer::properties::contributionError"
    }
    column "mat_phone" {
      type    = "String"
      comment = "column_materializer::properties::phone"
    }
    column "mat_$initial_pathname" {
      type    = "String"
      comment = "column_materializer::properties::$initial_pathname"
    }
    column "mat_organization_name" {
      type    = "String"
      comment = "column_materializer::properties::organization_name"
    }
    column "mat_category" {
      type    = "String"
      comment = "column_materializer::properties::category"
    }
    column "mat_$lib_version" {
      type    = "String"
      comment = "column_materializer::properties::$lib_version"
    }
    column "mat_pp_$initial_utm_campaign" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_utm_campaign"
    }
    column "mat_pp_$initial_utm_medium" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_utm_medium"
    }
    column "mat_pp_$initial_gclid" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_gclid"
    }
    column "mat_pp_$initial_gad_source" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_gad_source"
    }
    column "mat_pp_$initial_utm_source" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_utm_source"
    }
    column "mat_pp_$initial_referring_domain" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_referring_domain"
    }
    column "mat_pp_$initial_utm_term" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_utm_term"
    }
    column "mat_pp_$initial_utm_content" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_utm_content"
    }
    column "mat_pp_$initial_gbraid" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_gbraid::disabled"
    }
    column "mat_pp_$initial_wbraid" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_wbraid::disabled"
    }
    column "mat_pp_$initial_msclkid" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_msclkid"
    }
    column "mat_pp_$initial_fbclid" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_fbclid"
    }
    column "mat_$geoip_subdivision_1_code" {
      type    = "String"
      comment = "column_materializer::properties::$geoip_subdivision_1_code"
    }
    column "mat_wlo_enabled" {
      type    = "String"
      comment = "column_materializer::properties::wlo_enabled"
    }
    column "mat_$prev_pageview_max_scroll_percentage" {
      type    = "String"
      comment = "column_materializer::properties::$prev_pageview_max_scroll_percentage"
    }
    column "mat_$prev_pageview_max_content_percentage" {
      type    = "String"
      comment = "column_materializer::properties::$prev_pageview_max_content_percentage"
    }
    column "mat_$prev_pageview_pathname" {
      type    = "String"
      comment = "column_materializer::properties::$prev_pageview_pathname"
    }
    column "mat_pp_$initial_pathname" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_pathname"
    }
    column "mat_pp_$geoip_country_code" {
      type    = "String"
      comment = "column_materializer::person_properties::$geoip_country_code"
    }
    column "mat_pp_username" {
      type    = "String"
      comment = "column_materializer::person_properties::username"
    }
    column "mat_pp_serverMasterclass" {
      type    = "String"
      comment = "column_materializer::person_properties::serverMasterclass"
    }
    column "mat_content_length" {
      type    = "String"
      comment = "column_materializer::properties::content_length"
    }
    column "mat_pp_serverMarketing" {
      type    = "String"
      comment = "column_materializer::person_properties::serverMarketing"
    }
    column "mat_$browser_version" {
      type    = "String"
      comment = "column_materializer::properties::$browser_version"
    }
    column "mat_pp_role" {
      type    = "String"
      comment = "column_materializer::person_properties::role"
    }
    column "mat_pp_customer" {
      type    = "String"
      comment = "column_materializer::person_properties::customer"
    }
    column "mat_event" {
      type    = "String"
      comment = "column_materializer::properties::event"
    }
    column "mat_disable_institution_search" {
      type    = "String"
      comment = "column_materializer::properties::disable_institution_search"
    }
    column "mat_is_first_event_for_user" {
      type    = "String"
      comment = "column_materializer::properties::is_first_event_for_user"
    }
    column "mat_current_member_guid" {
      type    = "String"
      comment = "column_materializer::properties::current_member_guid"
    }
    column "mat_user_agent" {
      type    = "String"
      comment = "column_materializer::properties::user_agent"
    }
    column "mat_is_test_user" {
      type    = "String"
      comment = "column_materializer::properties::is_test_user"
    }
    column "mat_referrer" {
      type    = "String"
      comment = "column_materializer::properties::referrer"
    }
    column "mat_pp_$initial_current_url" {
      type    = "String"
      comment = "column_materializer::person_properties::$initial_current_url"
    }
    column "mat_most_recent_app_os" {
      type    = "String"
      comment = "column_materializer::properties::most_recent_app_os"
    }
    column "mat_pp_hubspot_score" {
      type    = "String"
      comment = "column_materializer::person_properties::hubspot_score"
    }
    column "mat_pp_id" {
      type    = "String"
      comment = "column_materializer::person_properties::id"
    }
    column "mat_pp_$current_url" {
      type    = "String"
      comment = "column_materializer::person_properties::$current_url"
    }
    column "mat_product_key" {
      type    = "String"
      comment = "column_materializer::properties::product_key"
    }
    column "mat_Plan_type_and_filter" {
      type    = "String"
      comment = "column_materializer::properties::Plan type and filter"
    }
    column "mat_$app_namespace" {
      type    = "String"
      comment = "column_materializer::properties::$app_namespace"
    }
    column "mat_$os_name" {
      type    = "String"
      comment = "column_materializer::properties::$os_name"
    }
    column "mat_pp_$os_name" {
      type    = "String"
      comment = "column_materializer::person_properties::$os_name::disabled"
    }
    column "mat_pp_$app_version" {
      type    = "String"
      comment = "column_materializer::person_properties::$app_version"
    }
    column "mat_subscriptionStatus" {
      type    = "String"
      comment = "column_materializer::properties::subscriptionStatus"
    }
    column "mat_$screen_height" {
      type    = "String"
      comment = "column_materializer::properties::$screen_height"
    }
    column "mat_$screen_width" {
      type    = "String"
      comment = "column_materializer::properties::$screen_width"
    }
    column "mat_tag" {
      type    = "String"
      comment = "column_materializer::properties::tag"
    }
    column "mat_$app_build" {
      type    = "String"
      comment = "column_materializer::properties::$app_build"
    }
    column "mat_surface_tag" {
      type    = "String"
      comment = "column_materializer::properties::surface_tag"
    }
    column "mat_survey_responses_count_in_period" {
      type    = "String"
      comment = "column_materializer::properties::survey_responses_count_in_period"
    }
    column "mat_event_count_in_month" {
      type    = "String"
      comment = "column_materializer::properties::event_count_in_month"
    }
    column "mat_ramp" {
      type    = "String"
      comment = "column_materializer::properties::ramp"
    }
    column "mat_auto_chapters" {
      type    = "String"
      comment = "column_materializer::properties::auto_chapters"
    }
    column "mat_sentiment_analysis" {
      type    = "String"
      comment = "column_materializer::properties::sentiment_analysis"
    }
    column "mat_redact_pii" {
      type    = "String"
      comment = "column_materializer::properties::redact_pii"
    }
    column "mat_content_safety" {
      type    = "String"
      comment = "column_materializer::properties::content_safety"
    }
    column "mat_iab_categories" {
      type    = "String"
      comment = "column_materializer::properties::iab_categories"
    }
    column "mat_auto_highlights" {
      type    = "String"
      comment = "column_materializer::properties::auto_highlights"
    }
    column "mat_entity_detection" {
      type    = "String"
      comment = "column_materializer::properties::entity_detection"
    }
    column "mat_summarization" {
      type    = "String"
      comment = "column_materializer::properties::summarization"
    }
    column "mat_pp_val_region" {
      type    = "String"
      comment = "column_materializer::person_properties::val_region"
    }
    column "mat_client_id" {
      type    = "String"
      comment = "column_materializer::properties::client_id"
    }
    column "mat_$geoip_country_code" {
      type    = "String"
      comment = "column_materializer::properties::$geoip_country_code"
    }
    column "mat_disfluencies" {
      type    = "String"
      comment = "column_materializer::properties::disfluencies"
    }
    column "mat_filter_profanity" {
      type    = "String"
      comment = "column_materializer::properties::filter_profanity"
    }
    column "mat_speaker_labels" {
      type    = "String"
      comment = "column_materializer::properties::speaker_labels"
    }
    column "mat_language_detection" {
      type    = "String"
      comment = "column_materializer::properties::language_detection"
    }
    column "mat_product_analytics_projected_amount" {
      type    = "String"
      comment = "column_materializer::properties::product_analytics_projected_amount"
    }
    column "mat_recordings_projected_amount" {
      type    = "String"
      comment = "column_materializer::properties::recordings_projected_amount"
    }
    column "mat_events_projected_amount" {
      type    = "String"
      comment = "column_materializer::properties::events_projected_amount"
    }
    column "mat_session_replay_projected_amount" {
      type    = "String"
      comment = "column_materializer::properties::session_replay_projected_amount"
    }
    column "mat_total_usd" {
      type    = "String"
      comment = "column_materializer::properties::total_usd"
    }
    column "mat_stripe_amount_paid" {
      type    = "String"
      comment = "column_materializer::properties::stripe_amount_paid"
    }
    column "mat_workspace" {
      type    = "String"
      comment = "column_materializer::properties::workspace"
    }
    column "mat_created_at" {
      type    = "String"
      comment = "column_materializer::properties::created_at"
    }
    column "mat_kind" {
      type    = "String"
      comment = "column_materializer::properties::kind"
    }
    column "mat_product" {
      type    = "String"
      comment = "column_materializer::properties::product"
    }
    column "mat_message" {
      type    = "String"
      comment = "column_materializer::properties::message"
    }
    column "mat_initiator" {
      type    = "String"
      comment = "column_materializer::properties::initiator"
    }
    column "mat_query" {
      type    = "String"
      comment = "column_materializer::properties::query"
    }
    column "mat_$survey_id" {
      type    = "String"
      comment = "column_materializer::properties::$survey_id"
    }
    column "mat_$survey_response_1" {
      type    = "String"
      comment = "column_materializer::properties::$survey_response_1"
    }
    column "mat_ticketId" {
      type    = "String"
      comment = "column_materializer::properties::ticketId"
    }
    column "mat_$survey_response" {
      type    = "String"
      comment = "column_materializer::properties::$survey_response"
    }
    column "mat_conceptName" {
      type    = "String"
      comment = "column_materializer::properties::conceptName"
    }
    column "mat_apiName" {
      type    = "String"
      comment = "column_materializer::properties::apiName"
    }
    column "mat_workplace_billing_plan" {
      type    = "String"
      comment = "column_materializer::properties::workplace_billing_plan"
    }
    column "mat_$el_text" {
      type    = "String"
      comment = "column_materializer::properties::$el_text"
    }
    column "mat_recording_count_in_period" {
      type    = "String"
      comment = "column_materializer::properties::recording_count_in_period"
    }
    column "mat_$os_version" {
      type    = "String"
      comment = "column_materializer::properties::$os_version"
    }
    column "mat_orderId" {
      type    = "String"
      comment = "column_materializer::properties::orderId"
    }
    column "mat_commit_sha" {
      type    = "String"
      comment = "column_materializer::properties::commit_sha"
    }
    column "mat_$feature_flag_payloads" {
      type    = "String"
      comment = "column_materializer::properties::$feature_flag_payloads"
    }
    column "mat_event_count_in_period" {
      type    = "String"
      comment = "column_materializer::properties::event_count_in_period"
    }
    column "mat_$groups" {
      type    = "String"
      comment = "column_materializer::properties::$groups"
    }
    column "mat_$feature_flag" {
      type    = "String"
      comment = "column_materializer::properties::$feature_flag"
    }
    column "mat_utm_content" {
      type    = "String"
      comment = "column_materializer::properties::utm_content"
    }
    column "mat_gclid" {
      type    = "String"
      comment = "column_materializer::properties::gclid"
    }
    column "mat_gad_source" {
      type    = "String"
      comment = "column_materializer::properties::gad_source"
    }
    column "mat_gbraid" {
      type    = "String"
      comment = "column_materializer::properties::gbraid"
    }
    column "mat_wbraid" {
      type    = "String"
      comment = "column_materializer::properties::wbraid"
    }
    column "mat_fbclid" {
      type    = "String"
      comment = "column_materializer::properties::fbclid"
    }
    column "mat_msclkid" {
      type    = "String"
      comment = "column_materializer::properties::msclkid"
    }
    column "mat_organization_id" {
      type    = "String"
      comment = "column_materializer::properties::organization_id"
    }
    column "mat_owner_type" {
      type    = "String"
      comment = "column_materializer::properties::owner_type"
    }
    column "mat_device_type" {
      type    = "String"
      comment = "column_materializer::properties::device_type"
    }
    column "mat_$device_id" {
      type    = "String"
      comment = "column_materializer::properties::$device_id"
    }
    column "mat_pp_$geoip_continent_name" {
      type    = "String"
      comment = "column_materializer::person_properties::$geoip_continent_name"
    }
    column "mat_$feature_flag_response" {
      type    = "String"
      comment = "column_materializer::properties::$feature_flag_response"
    }
    column "mat_pp_utm_source" {
      type    = "String"
      comment = "column_materializer::person_properties::utm_source"
    }
    column "mat_pp_$referring_domain" {
      type    = "String"
      comment = "column_materializer::person_properties::$referring_domain"
    }
    column "mat_pp_Email_Domain" {
      type    = "String"
      comment = "column_materializer::person_properties::Email Domain"
    }
    column "mat_machine_id" {
      type    = "String"
      comment = "column_materializer::properties::machine_id"
    }
    column "mat_user_email_domain" {
      type    = "String"
      comment = "column_materializer::properties::user_email_domain"
    }
    column "mat_$lib_version__minor" {
      type    = "String"
      comment = "column_materializer::properties::$lib_version__minor"
    }
    column "mat_region" {
      type    = "String"
      comment = "column_materializer::properties::region"
    }
    column "mat_pp_user_email_domain" {
      type    = "String"
      comment = "column_materializer::person_properties::user_email_domain"
    }
    column "mat_url_promotion_id" {
      type    = "String"
      comment = "column_materializer::properties::url_promotion_id"
    }
    column "mat_$lib_custom_api_host" {
      type    = "String"
      comment = "column_materializer::properties::$lib_custom_api_host"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "mat_user_platform" {
      type    = "String"
      comment = "column_materializer::properties::user_platform"
    }
    column "mat_pp_$geoip_country_name" {
      type    = "String"
      comment = "column_materializer::person_properties::$geoip_country_name"
    }
    column "mat_environment" {
      type    = "String"
      comment = "column_materializer::properties::environment"
    }
    column "mat_customer_email" {
      type    = "String"
      comment = "column_materializer::properties::customer_email"
    }
    column "mat_client_name" {
      type    = "String"
      comment = "column_materializer::properties::client_name"
    }
    column "mat_screen_name" {
      type    = "String"
      comment = "column_materializer::properties::screen_name"
    }
    column "mat_app_version" {
      type    = "String"
      comment = "column_materializer::properties::app_version"
    }
    column "elements_chain_href" {
      type    = "String"
      comment = "column_materializer::elements_chain::href"
    }
    column "elements_chain_texts" {
      type    = "Array(String)"
      comment = "column_materializer::elements_chain::texts"
    }
    column "elements_chain_ids" {
      type    = "Array(String)"
      comment = "column_materializer::elements_chain::ids"
    }
    column "elements_chain_elements" {
      type    = "Array(Enum8('a'=1, 'button'=2, 'form'=3, 'input'=4, 'select'=5, 'textarea'=6, 'label'=7))"
      comment = "column_materializer::elements_chain::elements"
    }
    column "properties_group_custom" {
      type = "Map(String, String)"
    }
    column "properties_group_feature_flags" {
      type = "Map(String, String)"
    }
    column "is_deleted" {
      type = "Bool"
    }
    column "mat_subdomain" {
      type    = "String"
      comment = "column_materializer::properties::subdomain"
    }
    column "mat_$device" {
      type    = "String"
      comment = "column_materializer::properties::$device"
    }
    column "mat_id" {
      type    = "String"
      comment = "column_materializer::properties::id"
    }
    column "mat_record_id" {
      type    = "String"
      comment = "column_materializer::properties::record_id"
    }
    column "mat_referrer_id" {
      type    = "String"
      comment = "column_materializer::properties::record_id"
    }
    column "mat_$exception_issue_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$exception_issue_id"
    }
    column "mat_$exception_fingerprint" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$exception_fingerprint"
    }
    column "mat_$web_vitals_LCP_value" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$web_vitals_LCP_value"
    }
    column "mat_$web_vitals_FCP_value" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$web_vitals_FCP_value"
    }
    column "mat_$web_vitals_CLS_value" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$web_vitals_CLS_value"
    }
    column "mat_$web_vitals_INP_value" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$web_vitals_INP_value"
    }
    column "mat_$viewport_width" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$viewport_width"
    }
    column "mat_$viewport_height" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$viewport_height"
    }
    column "mat_$anon_distinct_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$anon_distinct_id"
    }
    column "person_properties_map_custom" {
      type = "Map(String, String)"
    }
    column "mat_$ai_trace_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_trace_id"
    }
    column "mat_$ai_model" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_model"
    }
    column "mat_$ai_provider" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_provider"
    }
    column "mat_$ai_parent_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_parent_id"
    }
    column "mat_$ai_span_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_span_id"
    }
    column "mat_$ai_http_status" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_http_status"
    }
    column "mat_$exception_types" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$exception_types"
    }
    column "mat_$exception_values" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$exception_values"
    }
    column "mat_$exception_sources" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$exception_sources"
    }
    column "mat_$exception_functions" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$exception_functions"
    }
    column "$session_id_uuid" {
      type = "Nullable(UInt128)"
    }
    column "mat_$process_person_profile" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$process_person_profile"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
    column "properties_group_ai" {
      type = "Map(String, String)"
    }
    column "mat_$is_identified" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$is_identified"
    }
    column "mat_historical_migration" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::historical_migration"
    }
    column "mat_$ai_session_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_session_id"
    }
    column "mat_$ai_is_error" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_is_error"
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
    column "dmat_numeric_0" {
      type = "Nullable(Float64)"
    }
    column "dmat_numeric_1" {
      type = "Nullable(Float64)"
    }
    column "dmat_numeric_2" {
      type = "Nullable(Float64)"
    }
    column "dmat_numeric_3" {
      type = "Nullable(Float64)"
    }
    column "dmat_numeric_4" {
      type = "Nullable(Float64)"
    }
    column "dmat_numeric_5" {
      type = "Nullable(Float64)"
    }
    column "dmat_numeric_6" {
      type = "Nullable(Float64)"
    }
    column "dmat_numeric_7" {
      type = "Nullable(Float64)"
    }
    column "dmat_numeric_8" {
      type = "Nullable(Float64)"
    }
    column "dmat_numeric_9" {
      type = "Nullable(Float64)"
    }
    column "dmat_bool_0" {
      type = "Nullable(UInt8)"
    }
    column "dmat_bool_1" {
      type = "Nullable(UInt8)"
    }
    column "dmat_bool_2" {
      type = "Nullable(UInt8)"
    }
    column "dmat_bool_3" {
      type = "Nullable(UInt8)"
    }
    column "dmat_bool_4" {
      type = "Nullable(UInt8)"
    }
    column "dmat_bool_5" {
      type = "Nullable(UInt8)"
    }
    column "dmat_bool_6" {
      type = "Nullable(UInt8)"
    }
    column "dmat_bool_7" {
      type = "Nullable(UInt8)"
    }
    column "dmat_bool_8" {
      type = "Nullable(UInt8)"
    }
    column "dmat_bool_9" {
      type = "Nullable(UInt8)"
    }
    column "dmat_datetime_0" {
      type = "Nullable(DateTime64(6, 'UTC'))"
    }
    column "dmat_datetime_1" {
      type = "Nullable(DateTime64(6, 'UTC'))"
    }
    column "dmat_datetime_2" {
      type = "Nullable(DateTime64(6, 'UTC'))"
    }
    column "dmat_datetime_3" {
      type = "Nullable(DateTime64(6, 'UTC'))"
    }
    column "dmat_datetime_4" {
      type = "Nullable(DateTime64(6, 'UTC'))"
    }
    column "dmat_datetime_5" {
      type = "Nullable(DateTime64(6, 'UTC'))"
    }
    column "dmat_datetime_6" {
      type = "Nullable(DateTime64(6, 'UTC'))"
    }
    column "dmat_datetime_7" {
      type = "Nullable(DateTime64(6, 'UTC'))"
    }
    column "dmat_datetime_8" {
      type = "Nullable(DateTime64(6, 'UTC'))"
    }
    column "dmat_datetime_9" {
      type = "Nullable(DateTime64(6, 'UTC'))"
    }
    column "historical_migration" {
      type = "Bool"
    }
    column "mat_$ai_total_cost_usd" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_total_cost_usd"
    }
    column "properties_group_ai_large" {
      type = "Map(String, String)"
    }
    column "mat_$ai_prompt_name" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_prompt_name"
    }
    column "mat_$ai_experiment_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_experiment_id"
    }
    column "mat_$survey_submission_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$survey_submission_id"
    }
    column "mat_$geoip_subdivision_1_name" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$geoip_subdivision_1_name"
    }
    column "mat_$raw_user_agent" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$raw_user_agent"
    }
    column "mat_$prev_pageview_duration" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$prev_pageview_duration"
    }
    column "mat_pp_$initial_host" {
      type    = "Nullable(String)"
      comment = "column_materializer::person_properties::$initial_host"
    }
    column "mat_pp_$initial_url" {
      type    = "Nullable(String)"
      comment = "column_materializer::person_properties::$initial_url"
    }
    column "mat_pp_$initial_geoip_country_name" {
      type    = "Nullable(String)"
      comment = "column_materializer::person_properties::$initial_geoip_country_name"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_events"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }
  table "raw_sessions_v3" {
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
      type    = "DateTime64(3)"
      default = "fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80)))"
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
    column "hosts" {
      type = "SimpleAggregateFunction(groupUniqArrayArray(100), Array(String))"
    }
    column "emails" {
      type = "SimpleAggregateFunction(groupUniqArrayArray(10), Array(String))"
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
      zoo_path     = "/clickhouse/tables/sessions/noshard/posthog.raw_sessions_v3"
      replica_name = "{shard}-{replica}"
    }
  }
}

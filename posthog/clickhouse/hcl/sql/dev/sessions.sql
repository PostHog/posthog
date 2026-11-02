-- AUTO-GENERATED from the declarative HCL by ops/gen-sql.sh — do not edit.
-- Full CREATE schema for the dev/sessions node. Apply to a fresh ClickHouse to build it.

CREATE TABLE posthog.channel_definition (
  domain String,
  kind String,
  domain_type Nullable(String),
  type_if_paid Nullable(String),
  type_if_organic Nullable(String)
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/sessions/noshard/posthog.channel_definition', '{replica}-{shard}') ORDER BY (domain, kind) SETTINGS default_compression_codec = 'lz4', index_granularity = 8192;
CREATE TABLE posthog.cohortpeople (
  person_id UUID,
  cohort_id Int64,
  team_id Int64,
  sign Int8,
  version UInt64
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'cohortpeople', rand());
CREATE TABLE posthog.events (
  uuid UUID,
  event String,
  properties String,
  timestamp DateTime64(6, 'UTC'),
  team_id Int64,
  distinct_id String,
  elements_hash String,
  created_at DateTime64(6, 'UTC'),
  _timestamp DateTime,
  _offset UInt64,
  elements_chain String,
  $group_0 String COMMENT 'column_materializer::$group_0',
  $group_1 String COMMENT 'column_materializer::$group_1',
  $group_2 String COMMENT 'column_materializer::$group_2',
  $group_3 String COMMENT 'column_materializer::$group_3',
  $group_4 String COMMENT 'column_materializer::$group_4',
  $window_id String COMMENT 'column_materializer::$window_id',
  $session_id String COMMENT 'column_materializer::$session_id',
  group_0 String ALIAS `$group_0`,
  group_1 String ALIAS `$group_1`,
  group_2 String ALIAS `$group_2`,
  group_3 String ALIAS `$group_3`,
  group_4 String ALIAS `$group_4`,
  person_id UUID,
  person_properties String,
  group0_properties String,
  group1_properties String,
  group2_properties String,
  group3_properties String,
  group4_properties String,
  person_created_at DateTime64(3),
  group0_created_at DateTime64(3),
  group1_created_at DateTime64(3),
  group2_created_at DateTime64(3),
  group3_created_at DateTime64(3),
  group4_created_at DateTime64(3),
  inserted_at Nullable(DateTime64(6, 'UTC')) DEFAULT now64(),
  person_mode Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2),
  elements_chain_href String COMMENT 'column_materializer::elements_chain::href',
  elements_chain_texts Array(String) COMMENT 'column_materializer::elements_chain::texts',
  elements_chain_ids Array(String) COMMENT 'column_materializer::elements_chain::ids',
  elements_chain_elements Array(Enum8('a'=1, 'button'=2, 'form'=3, 'input'=4, 'select'=5, 'textarea'=6, 'label'=7)) COMMENT 'column_materializer::elements_chain::elements',
  properties_group_custom Map(String, String),
  properties_group_feature_flags Map(String, String),
  is_deleted Bool,
  person_properties_map_custom Map(String, String),
  mat_$ai_trace_id Nullable(String) COMMENT 'column_materializer::properties::$ai_trace_id',
  $session_id_uuid Nullable(UInt128),
  consumer_breadcrumbs Array(String),
  properties_group_ai Map(String, String),
  mat_historical_migration Nullable(String) COMMENT 'column_materializer::properties::historical_migration',
  mat_$ai_session_id Nullable(String) COMMENT 'column_materializer::properties::$ai_session_id',
  mat_$ai_is_error Nullable(String) COMMENT 'column_materializer::properties::$ai_is_error',
  dmat_string_0 Nullable(String),
  dmat_string_1 Nullable(String),
  dmat_string_2 Nullable(String),
  dmat_string_3 Nullable(String),
  dmat_string_4 Nullable(String),
  dmat_string_5 Nullable(String),
  dmat_string_6 Nullable(String),
  dmat_string_7 Nullable(String),
  dmat_string_8 Nullable(String),
  dmat_string_9 Nullable(String),
  historical_migration Bool,
  properties_group_ai_large Map(String, String),
  mat_$ai_prompt_name Nullable(String) COMMENT 'column_materializer::properties::$ai_prompt_name'
) ENGINE = Distributed('posthog', 'posthog', 'sharded_events', sipHash64(distinct_id));
CREATE TABLE posthog.person_distinct_id_overrides (
  team_id Int64,
  distinct_id String,
  person_id UUID,
  is_deleted Int8,
  version Int64,
  _timestamp DateTime,
  _offset UInt64,
  _partition UInt64
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'person_distinct_id_overrides', sipHash64(distinct_id));
CREATE TABLE posthog.person_static_cohort (
  id UUID,
  person_id UUID,
  cohort_id Int64,
  team_id Int64,
  _timestamp DateTime,
  _offset UInt64
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'person_static_cohort', rand());
CREATE TABLE posthog.query_log_archive (
  initial_query_start_time DateTime64(6, 'UTC'),
  team_id Int64,
  initial_query_id String,
  is_initial_query SimpleAggregateFunction(max, UInt8),
  hostname SimpleAggregateFunction(max, LowCardinality(String)),
  user SimpleAggregateFunction(max, LowCardinality(String)),
  type SimpleAggregateFunction(max, Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4)),
  event_time_microseconds SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
  query_duration_ms SimpleAggregateFunction(max, UInt64),
  read_rows SimpleAggregateFunction(sum, UInt64),
  read_bytes SimpleAggregateFunction(sum, UInt64),
  written_rows SimpleAggregateFunction(sum, UInt64),
  written_bytes SimpleAggregateFunction(sum, UInt64),
  result_rows SimpleAggregateFunction(sum, UInt64),
  result_bytes SimpleAggregateFunction(sum, UInt64),
  memory_usage SimpleAggregateFunction(max, UInt64),
  memory_usage_sum SimpleAggregateFunction(sum, UInt64),
  peak_threads_usage SimpleAggregateFunction(sum, UInt64),
  execution_count SimpleAggregateFunction(sum, UInt64),
  current_database SimpleAggregateFunction(max, LowCardinality(String)),
  query SimpleAggregateFunction(max, String),
  normalized_query_hash SimpleAggregateFunction(max, UInt64),
  query_kind_by_root SimpleAggregateFunction(max, Tuple(UInt8, String)),
  tables SimpleAggregateFunction(max, Array(String)),
  exception_code SimpleAggregateFunction(max, Int32),
  exception SimpleAggregateFunction(max, String),
  stack_trace SimpleAggregateFunction(max, String),
  ProfileEvents_SelectedRows SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SelectedBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_RealTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_OSCPUVirtualTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_UserTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SystemTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SelectedParts SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SelectedMarks SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_NetworkReceiveBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_NetworkSendBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_ReadBufferFromFileDescriptorReadBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_WriteBufferFromFileDescriptorWriteBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3Clients SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3DeleteObjects SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3CopyObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3ListObjects SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3HeadObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3GetObjectAttributes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3CreateMultipartUpload SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3UploadPartCopy SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3UploadPart SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3AbortMultipartUpload SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3CompleteMultipartUpload SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3PutObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3GetObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_ReadBufferFromS3Bytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_WriteBufferFromS3Bytes SimpleAggregateFunction(sum, UInt64),
  lc_org_id SimpleAggregateFunction(max, String),
  lc_user_id SimpleAggregateFunction(max, Int64),
  lc_session_id SimpleAggregateFunction(max, String),
  lc_is_impersonated SimpleAggregateFunction(max, Bool),
  lc_workflow SimpleAggregateFunction(max, LowCardinality(String)),
  lc_kind SimpleAggregateFunction(max, LowCardinality(String)),
  lc_id SimpleAggregateFunction(max, String),
  lc_route_id SimpleAggregateFunction(max, String),
  lc_access_method SimpleAggregateFunction(max, LowCardinality(String)),
  lc_api_key_label SimpleAggregateFunction(max, String),
  lc_api_key_mask SimpleAggregateFunction(max, String),
  lc_query_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_product SimpleAggregateFunction(max, LowCardinality(String)),
  lc_chargeable SimpleAggregateFunction(max, Bool),
  lc_name SimpleAggregateFunction(max, String),
  lc_request_name SimpleAggregateFunction(max, String),
  lc_client_query_id SimpleAggregateFunction(max, String),
  lc_dashboard_id SimpleAggregateFunction(max, Int64),
  lc_insight_id SimpleAggregateFunction(max, Int64),
  lc_cohort_id SimpleAggregateFunction(max, Int64),
  lc_batch_export_id SimpleAggregateFunction(max, String),
  lc_experiment_id SimpleAggregateFunction(max, Int64),
  lc_experiment_feature_flag_key SimpleAggregateFunction(max, String),
  lc_alert_config_id SimpleAggregateFunction(max, String),
  lc_feature SimpleAggregateFunction(max, LowCardinality(String)),
  lc_table_id SimpleAggregateFunction(max, String),
  lc_warehouse_query SimpleAggregateFunction(max, Bool),
  lc_person_on_events_mode SimpleAggregateFunction(max, LowCardinality(String)),
  lc_service_name SimpleAggregateFunction(max, LowCardinality(String)),
  lc_workload SimpleAggregateFunction(max, LowCardinality(String)),
  lc_query__kind SimpleAggregateFunction(max, LowCardinality(String)),
  lc_query__query SimpleAggregateFunction(max, String),
  lc_query SimpleAggregateFunction(max, String),
  lc_modifiers SimpleAggregateFunction(max, String),
  lc_temporal__workflow_namespace SimpleAggregateFunction(max, LowCardinality(String)),
  lc_temporal__workflow_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_temporal__workflow_id SimpleAggregateFunction(max, String),
  lc_temporal__workflow_run_id SimpleAggregateFunction(max, String),
  lc_temporal__activity_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_temporal__activity_id SimpleAggregateFunction(max, String),
  lc_temporal__attempt SimpleAggregateFunction(max, Int64),
  lc_dagster__job_name SimpleAggregateFunction(max, LowCardinality(String)),
  lc_dagster__run_id SimpleAggregateFunction(max, String),
  lc_dagster__owner SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_name SimpleAggregateFunction(max, String),
  lc_experiment_metric_name SimpleAggregateFunction(max, String),
  lc_experiment_execution_path SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_metric_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_funnel_order_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_exposures_path SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_metric_events_path SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_query_surface SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_precompute_table SimpleAggregateFunction(max, String),
  lc_experiment_query_group_id SimpleAggregateFunction(max, String),
  lc_experiment_precompute_skip_reason SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_scan_date_from SimpleAggregateFunction(max, String),
  lc_experiment_scan_date_to SimpleAggregateFunction(max, String),
  lc_precompute_window_start SimpleAggregateFunction(max, String),
  lc_precompute_window_end SimpleAggregateFunction(max, String),
  lc_plan_fingerprint SimpleAggregateFunction(max, String),
  lc_estimated_rows SimpleAggregateFunction(max, Int64),
  lc_estimated_bytes SimpleAggregateFunction(max, Int64),
  query_id String,
  event_time DateTime('UTC'),
  event_date Date,
  query_start_time DateTime('UTC'),
  query_start_time_microseconds DateTime64(6, 'UTC'),
  query_kind LowCardinality(String),
  formatted_query String,
  query_shape String,
  hogql_shape String,
  exception_name String,
  ProfileEvents Map(String, UInt64)
) ENGINE = Distributed('ops', 'posthog', 'sharded_query_log_archive_v3');
CREATE TABLE posthog.raw_sessions (
  team_id Int64,
  session_id_v7 UInt128,
  distinct_id AggregateFunction(argMax, String, DateTime64(6, 'UTC')),
  min_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
  max_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
  max_inserted_at SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
  urls SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
  entry_url AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  end_url AggregateFunction(argMax, String, DateTime64(6, 'UTC')),
  last_external_click_url AggregateFunction(argMax, String, DateTime64(6, 'UTC')),
  initial_browser AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_browser_version AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_os AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_os_version AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_device_type AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_viewport_width AggregateFunction(argMin, Int64, DateTime64(6, 'UTC')),
  initial_viewport_height AggregateFunction(argMin, Int64, DateTime64(6, 'UTC')),
  initial_geoip_country_code AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_geoip_subdivision_1_code AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_geoip_subdivision_1_name AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_geoip_subdivision_city_name AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_geoip_time_zone AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_referring_domain AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_utm_source AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_utm_campaign AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_utm_medium AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_utm_term AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_utm_content AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_gclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_gad_source AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_gclsrc AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_dclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_gbraid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_wbraid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_fbclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_msclkid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_twclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_li_fat_id AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_mc_cid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_igshid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_ttclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_irclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  pageview_count SimpleAggregateFunction(sum, Int64),
  pageview_uniq AggregateFunction(uniq, Nullable(UUID)),
  autocapture_count SimpleAggregateFunction(sum, Int64),
  autocapture_uniq AggregateFunction(uniq, Nullable(UUID)),
  screen_count SimpleAggregateFunction(sum, Int64),
  screen_uniq AggregateFunction(uniq, Nullable(UUID)),
  maybe_has_session_replay SimpleAggregateFunction(max, Bool),
  page_screen_autocapture_uniq_up_to AggregateFunction(uniqUpTo(1), Nullable(UUID)),
  vitals_lcp AggregateFunction(argMin, Nullable(Float64), DateTime64(6, 'UTC')),
  initial__kx AggregateFunction(argMin, String, DateTime64(6, 'UTC'))
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/sessions/noshard/posthog.raw_sessions', '{shard}-{replica}') ORDER BY (team_id, toStartOfHour(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000))), cityHash64(session_id_v7), session_id_v7) PARTITION BY toYYYYMM(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000))) SAMPLE BY cityHash64(session_id_v7) SETTINGS index_granularity = 8192;
CREATE TABLE posthog.raw_sessions_v3 (
  team_id Int64,
  session_id_v7 UInt128,
  session_timestamp DateTime64(3) DEFAULT fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80))),
  distinct_id AggregateFunction(argMax, String, DateTime64(6, 'UTC')),
  distinct_ids AggregateFunction(groupUniqArray, String),
  min_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
  max_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
  max_inserted_at SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
  urls SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String)),
  entry_url AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  end_url AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC')),
  last_external_click_url AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC')),
  browser AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  browser_version AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  os AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  os_version AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  device_type AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  viewport_width AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC')),
  viewport_height AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC')),
  geoip_country_code AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  geoip_subdivision_1_code AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  geoip_subdivision_1_name AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  geoip_subdivision_city_name AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  geoip_time_zone AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  entry_referring_domain AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  entry_utm_source AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  entry_utm_campaign AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  entry_utm_medium AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  entry_utm_term AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  entry_utm_content AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  entry_gclid AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  entry_gad_source AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  entry_fbclid AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  entry_has_gclid AggregateFunction(argMin, Bool, DateTime64(6, 'UTC')),
  entry_has_fbclid AggregateFunction(argMin, Bool, DateTime64(6, 'UTC')),
  entry_ad_ids_set AggregateFunction(argMin, Array(String), DateTime64(6, 'UTC')),
  entry_channel_type_properties AggregateFunction(argMin, Tuple(Nullable(String), Nullable(String), Nullable(String), Nullable(String), Bool, Bool, Nullable(String)), DateTime64(6, 'UTC')),
  pageview_uniq AggregateFunction(uniq, Nullable(UUID)),
  autocapture_uniq AggregateFunction(uniq, Nullable(UUID)),
  screen_uniq AggregateFunction(uniq, Nullable(UUID)),
  page_screen_uniq_up_to AggregateFunction(uniqUpTo(1), Nullable(UUID)),
  has_autocapture SimpleAggregateFunction(max, Bool),
  flag_key_values SimpleAggregateFunction(groupUniqArrayArray(10000), Array(String)),
  event_names SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
  hosts SimpleAggregateFunction(groupUniqArrayArray(100), Array(String)),
  emails SimpleAggregateFunction(groupUniqArrayArray(10), Array(String)),
  has_replay_events SimpleAggregateFunction(max, Bool),
  INDEX event_names_bloom_filter event_names TYPE bloom_filter() GRANULARITY 1,
  INDEX flag_key_values_text flag_key_values TYPE text(tokenizer = splitByString(['='])) GRANULARITY 100000000
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/sessions/noshard/posthog.raw_sessions_v3', '{shard}-{replica}') ORDER BY (team_id, session_timestamp, session_id_v7) PARTITION BY toYYYYMM(session_timestamp) SETTINGS index_granularity = 8192, storage_policy = 's3_tiered';
CREATE TABLE posthog.sessions (
  session_id String,
  team_id Int64,
  distinct_id SimpleAggregateFunction(any, String),
  min_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
  max_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
  urls SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
  entry_url AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  exit_url AggregateFunction(argMax, String, DateTime64(6, 'UTC')),
  initial_referring_domain AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_utm_source AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_utm_campaign AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_utm_medium AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_utm_term AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_utm_content AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_gclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_gad_source AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_gclsrc AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_dclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_gbraid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_wbraid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_fbclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_msclkid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_twclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_li_fat_id AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_mc_cid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_igshid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  initial_ttclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
  event_count_map SimpleAggregateFunction(sumMap, Map(String, Int64)),
  pageview_count SimpleAggregateFunction(sum, Int64),
  autocapture_count SimpleAggregateFunction(sum, Int64)
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/sessions/noshard/posthog.sessions', '{shard}-{replica}') ORDER BY (toStartOfDay(min_timestamp), team_id, session_id) PARTITION BY toYYYYMM(min_timestamp) SETTINGS index_granularity = 512;
CREATE TABLE posthog.web_pre_aggregated_teams (
  team_id UInt64,
  enabled_by String DEFAULT 'system',
  version UInt32 DEFAULT toUnixTimestamp(now())
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'web_pre_aggregated_teams');
CREATE TABLE posthog.writable_query_log_archive_v3 (
  initial_query_start_time DateTime64(6, 'UTC'),
  team_id Int64,
  initial_query_id String,
  is_initial_query SimpleAggregateFunction(max, UInt8),
  hostname SimpleAggregateFunction(max, LowCardinality(String)),
  user SimpleAggregateFunction(max, LowCardinality(String)),
  type SimpleAggregateFunction(max, Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4)),
  event_time_microseconds SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
  query_duration_ms SimpleAggregateFunction(max, UInt64),
  read_rows SimpleAggregateFunction(sum, UInt64),
  read_bytes SimpleAggregateFunction(sum, UInt64),
  written_rows SimpleAggregateFunction(sum, UInt64),
  written_bytes SimpleAggregateFunction(sum, UInt64),
  result_rows SimpleAggregateFunction(sum, UInt64),
  result_bytes SimpleAggregateFunction(sum, UInt64),
  memory_usage SimpleAggregateFunction(max, UInt64),
  memory_usage_sum SimpleAggregateFunction(sum, UInt64),
  peak_threads_usage SimpleAggregateFunction(sum, UInt64),
  execution_count SimpleAggregateFunction(sum, UInt64),
  current_database SimpleAggregateFunction(max, LowCardinality(String)),
  query SimpleAggregateFunction(max, String),
  normalized_query_hash SimpleAggregateFunction(max, UInt64),
  query_kind_by_root SimpleAggregateFunction(max, Tuple(UInt8, String)),
  tables SimpleAggregateFunction(max, Array(String)),
  exception_code SimpleAggregateFunction(max, Int32),
  exception SimpleAggregateFunction(max, String),
  stack_trace SimpleAggregateFunction(max, String),
  ProfileEvents_SelectedRows SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SelectedBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_RealTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_OSCPUVirtualTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_UserTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SystemTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SelectedParts SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SelectedMarks SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_NetworkReceiveBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_NetworkSendBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_ReadBufferFromFileDescriptorReadBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_WriteBufferFromFileDescriptorWriteBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3Clients SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3DeleteObjects SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3CopyObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3ListObjects SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3HeadObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3GetObjectAttributes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3CreateMultipartUpload SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3UploadPartCopy SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3UploadPart SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3AbortMultipartUpload SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3CompleteMultipartUpload SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3PutObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3GetObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_ReadBufferFromS3Bytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_WriteBufferFromS3Bytes SimpleAggregateFunction(sum, UInt64),
  lc_org_id SimpleAggregateFunction(max, String),
  lc_user_id SimpleAggregateFunction(max, Int64),
  lc_session_id SimpleAggregateFunction(max, String),
  lc_is_impersonated SimpleAggregateFunction(max, Bool),
  lc_workflow SimpleAggregateFunction(max, LowCardinality(String)),
  lc_kind SimpleAggregateFunction(max, LowCardinality(String)),
  lc_id SimpleAggregateFunction(max, String),
  lc_route_id SimpleAggregateFunction(max, String),
  lc_access_method SimpleAggregateFunction(max, LowCardinality(String)),
  lc_api_key_label SimpleAggregateFunction(max, String),
  lc_api_key_mask SimpleAggregateFunction(max, String),
  lc_query_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_product SimpleAggregateFunction(max, LowCardinality(String)),
  lc_chargeable SimpleAggregateFunction(max, Bool),
  lc_name SimpleAggregateFunction(max, String),
  lc_request_name SimpleAggregateFunction(max, String),
  lc_client_query_id SimpleAggregateFunction(max, String),
  lc_dashboard_id SimpleAggregateFunction(max, Int64),
  lc_insight_id SimpleAggregateFunction(max, Int64),
  lc_cohort_id SimpleAggregateFunction(max, Int64),
  lc_batch_export_id SimpleAggregateFunction(max, String),
  lc_experiment_id SimpleAggregateFunction(max, Int64),
  lc_experiment_feature_flag_key SimpleAggregateFunction(max, String),
  lc_alert_config_id SimpleAggregateFunction(max, String),
  lc_feature SimpleAggregateFunction(max, LowCardinality(String)),
  lc_table_id SimpleAggregateFunction(max, String),
  lc_warehouse_query SimpleAggregateFunction(max, Bool),
  lc_person_on_events_mode SimpleAggregateFunction(max, LowCardinality(String)),
  lc_service_name SimpleAggregateFunction(max, LowCardinality(String)),
  lc_workload SimpleAggregateFunction(max, LowCardinality(String)),
  lc_query__kind SimpleAggregateFunction(max, LowCardinality(String)),
  lc_query__query SimpleAggregateFunction(max, String),
  lc_query SimpleAggregateFunction(max, String),
  lc_modifiers SimpleAggregateFunction(max, String),
  lc_temporal__workflow_namespace SimpleAggregateFunction(max, LowCardinality(String)),
  lc_temporal__workflow_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_temporal__workflow_id SimpleAggregateFunction(max, String),
  lc_temporal__workflow_run_id SimpleAggregateFunction(max, String),
  lc_temporal__activity_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_temporal__activity_id SimpleAggregateFunction(max, String),
  lc_temporal__attempt SimpleAggregateFunction(max, Int64),
  lc_dagster__job_name SimpleAggregateFunction(max, LowCardinality(String)),
  lc_dagster__run_id SimpleAggregateFunction(max, String),
  lc_dagster__owner SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_name SimpleAggregateFunction(max, String),
  lc_experiment_metric_name SimpleAggregateFunction(max, String),
  lc_experiment_execution_path SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_metric_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_funnel_order_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_exposures_path SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_metric_events_path SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_query_surface SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_precompute_table SimpleAggregateFunction(max, String),
  lc_experiment_query_group_id SimpleAggregateFunction(max, String),
  lc_experiment_precompute_skip_reason SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_scan_date_from SimpleAggregateFunction(max, String),
  lc_experiment_scan_date_to SimpleAggregateFunction(max, String),
  lc_precompute_window_start SimpleAggregateFunction(max, String),
  lc_precompute_window_end SimpleAggregateFunction(max, String),
  lc_plan_fingerprint SimpleAggregateFunction(max, String),
  lc_estimated_rows SimpleAggregateFunction(max, Int64),
  lc_estimated_bytes SimpleAggregateFunction(max, Int64)
) ENGINE = Distributed('ops', 'posthog', 'query_log_archive_v3_buffer');
CREATE MATERIALIZED VIEW posthog.ops_query_log_archive_v3_mv TO posthog.writable_query_log_archive_v3 (initial_query_start_time DateTime64(6, 'UTC'), team_id Int64, initial_query_id String, is_initial_query SimpleAggregateFunction(max, UInt8), hostname SimpleAggregateFunction(max, LowCardinality(String)), user SimpleAggregateFunction(max, LowCardinality(String)), type SimpleAggregateFunction(max, Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4)), event_time_microseconds SimpleAggregateFunction(max, DateTime64(6, 'UTC')), query_duration_ms SimpleAggregateFunction(max, UInt64), read_rows SimpleAggregateFunction(sum, UInt64), read_bytes SimpleAggregateFunction(sum, UInt64), written_rows SimpleAggregateFunction(sum, UInt64), written_bytes SimpleAggregateFunction(sum, UInt64), result_rows SimpleAggregateFunction(sum, UInt64), result_bytes SimpleAggregateFunction(sum, UInt64), memory_usage SimpleAggregateFunction(max, UInt64), memory_usage_sum SimpleAggregateFunction(sum, UInt64), peak_threads_usage SimpleAggregateFunction(sum, UInt64), execution_count SimpleAggregateFunction(sum, UInt64), current_database SimpleAggregateFunction(max, LowCardinality(String)), query SimpleAggregateFunction(max, String), normalized_query_hash SimpleAggregateFunction(max, UInt64), query_kind_by_root SimpleAggregateFunction(max, Tuple(UInt8, String)), tables SimpleAggregateFunction(max, Array(String)), exception_code SimpleAggregateFunction(max, Int32), exception SimpleAggregateFunction(max, String), stack_trace SimpleAggregateFunction(max, String), ProfileEvents_SelectedRows SimpleAggregateFunction(sum, UInt64), ProfileEvents_SelectedBytes SimpleAggregateFunction(sum, UInt64), ProfileEvents_RealTimeMicroseconds SimpleAggregateFunction(sum, UInt64), ProfileEvents_OSCPUVirtualTimeMicroseconds SimpleAggregateFunction(sum, UInt64), ProfileEvents_UserTimeMicroseconds SimpleAggregateFunction(sum, UInt64), ProfileEvents_SystemTimeMicroseconds SimpleAggregateFunction(sum, UInt64), ProfileEvents_SelectedParts SimpleAggregateFunction(sum, UInt64), ProfileEvents_SelectedMarks SimpleAggregateFunction(sum, UInt64), ProfileEvents_NetworkReceiveBytes SimpleAggregateFunction(sum, UInt64), ProfileEvents_NetworkSendBytes SimpleAggregateFunction(sum, UInt64), ProfileEvents_ReadBufferFromFileDescriptorReadBytes SimpleAggregateFunction(sum, UInt64), ProfileEvents_WriteBufferFromFileDescriptorWriteBytes SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3Clients SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3DeleteObjects SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3CopyObject SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3ListObjects SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3HeadObject SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3GetObjectAttributes SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3CreateMultipartUpload SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3UploadPartCopy SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3UploadPart SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3AbortMultipartUpload SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3CompleteMultipartUpload SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3PutObject SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3GetObject SimpleAggregateFunction(sum, UInt64), ProfileEvents_ReadBufferFromS3Bytes SimpleAggregateFunction(sum, UInt64), ProfileEvents_WriteBufferFromS3Bytes SimpleAggregateFunction(sum, UInt64), lc_org_id SimpleAggregateFunction(max, String), lc_user_id SimpleAggregateFunction(max, Int64), lc_session_id SimpleAggregateFunction(max, String), lc_is_impersonated SimpleAggregateFunction(max, Bool), lc_workflow SimpleAggregateFunction(max, LowCardinality(String)), lc_kind SimpleAggregateFunction(max, LowCardinality(String)), lc_id SimpleAggregateFunction(max, String), lc_route_id SimpleAggregateFunction(max, String), lc_access_method SimpleAggregateFunction(max, LowCardinality(String)), lc_api_key_label SimpleAggregateFunction(max, String), lc_api_key_mask SimpleAggregateFunction(max, String), lc_query_type SimpleAggregateFunction(max, LowCardinality(String)), lc_product SimpleAggregateFunction(max, LowCardinality(String)), lc_chargeable SimpleAggregateFunction(max, Bool), lc_name SimpleAggregateFunction(max, String), lc_request_name SimpleAggregateFunction(max, String), lc_client_query_id SimpleAggregateFunction(max, String), lc_dashboard_id SimpleAggregateFunction(max, Int64), lc_insight_id SimpleAggregateFunction(max, Int64), lc_cohort_id SimpleAggregateFunction(max, Int64), lc_batch_export_id SimpleAggregateFunction(max, String), lc_experiment_id SimpleAggregateFunction(max, Int64), lc_experiment_feature_flag_key SimpleAggregateFunction(max, String), lc_alert_config_id SimpleAggregateFunction(max, String), lc_feature SimpleAggregateFunction(max, LowCardinality(String)), lc_table_id SimpleAggregateFunction(max, String), lc_warehouse_query SimpleAggregateFunction(max, Bool), lc_person_on_events_mode SimpleAggregateFunction(max, LowCardinality(String)), lc_service_name SimpleAggregateFunction(max, LowCardinality(String)), lc_workload SimpleAggregateFunction(max, LowCardinality(String)), lc_query__kind SimpleAggregateFunction(max, LowCardinality(String)), lc_query__query SimpleAggregateFunction(max, String), lc_query SimpleAggregateFunction(max, String), lc_modifiers SimpleAggregateFunction(max, String), lc_temporal__workflow_namespace SimpleAggregateFunction(max, LowCardinality(String)), lc_temporal__workflow_type SimpleAggregateFunction(max, LowCardinality(String)), lc_temporal__workflow_id SimpleAggregateFunction(max, String), lc_temporal__workflow_run_id SimpleAggregateFunction(max, String), lc_temporal__activity_type SimpleAggregateFunction(max, LowCardinality(String)), lc_temporal__activity_id SimpleAggregateFunction(max, String), lc_temporal__attempt SimpleAggregateFunction(max, Int64), lc_dagster__job_name SimpleAggregateFunction(max, LowCardinality(String)), lc_dagster__run_id SimpleAggregateFunction(max, String), lc_dagster__owner SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_name SimpleAggregateFunction(max, String), lc_experiment_metric_name SimpleAggregateFunction(max, String), lc_experiment_execution_path SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_metric_type SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_funnel_order_type SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_exposures_path SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_metric_events_path SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_query_surface SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_precompute_table SimpleAggregateFunction(max, String), lc_experiment_query_group_id SimpleAggregateFunction(max, String), lc_experiment_precompute_skip_reason SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_scan_date_from SimpleAggregateFunction(max, String), lc_experiment_scan_date_to SimpleAggregateFunction(max, String), lc_precompute_window_start SimpleAggregateFunction(max, String), lc_precompute_window_end SimpleAggregateFunction(max, String), lc_plan_fingerprint SimpleAggregateFunction(max, String), lc_estimated_rows SimpleAggregateFunction(max, Int64), lc_estimated_bytes SimpleAggregateFunction(max, Int64)) AS WITH
  JSONExtract(ql.log_comment, 'Tuple(team_id Int64, org_id String, user_id Int64, session_id String, is_impersonated Bool, workflow String, kind String, id String, route_id String, access_method String, api_key_label String, api_key_mask String, query_type String, product String, chargeable Bool, name String, request_name String, client_query_id String, dashboard_id Int64, insight_id Int64, cohort_id Int64, batch_export_id String, experiment_id Int64, experiment_feature_flag_key String, alert_config_id String, feature String, table_id String, warehouse_query Bool, person_on_events_mode String, service_name String, workload String, experiment_name String, experiment_metric_name String, experiment_execution_path String, experiment_metric_type String, experiment_funnel_order_type String, experiment_exposures_path String, experiment_metric_events_path String, experiment_query_surface String, experiment_precompute_table String, experiment_query_group_id String, experiment_precompute_skip_reason String, experiment_scan_date_from String, experiment_scan_date_to String, precompute_window_start String, precompute_window_end String, plan_fingerprint String, estimated_rows Int64, estimated_bytes Int64, temporal Tuple(workflow_namespace String, workflow_type String, workflow_id String, workflow_run_id String, activity_type String, activity_id String, attempt Int64), dagster Tuple(job_name String, run_id String, tags Tuple(owner String)), query Tuple(kind String, query String, source Tuple(kind String, query String)))') AS lc
SELECT
  if(
    empty(ql.initial_query_id),
    ql.query_start_time_microseconds,
    ql.initial_query_start_time_microseconds
  ) AS initial_query_start_time,
  lc.team_id AS team_id,
  if(empty(ql.initial_query_id), ql.query_id, ql.initial_query_id) AS initial_query_id,
  ql.is_initial_query AS is_initial_query,
  if(ql.is_initial_query, ql.hostname, '') AS hostname,
  ql.user AS user,
  ql.type AS type,
  ql.event_time_microseconds AS event_time_microseconds,
  if(ql.is_initial_query, ql.query_duration_ms, 0) AS query_duration_ms,
  if(ql.is_initial_query, ql.read_rows, 0) AS read_rows,
  if(ql.is_initial_query, ql.read_bytes, 0) AS read_bytes,
  if(ql.is_initial_query, ql.written_rows, 0) AS written_rows,
  if(ql.is_initial_query, ql.written_bytes, 0) AS written_bytes,
  if(ql.is_initial_query, ql.result_rows, 0) AS result_rows,
  if(ql.is_initial_query, ql.result_bytes, 0) AS result_bytes,
  ql.memory_usage AS memory_usage,
  ql.memory_usage AS memory_usage_sum,
  ql.peak_threads_usage AS peak_threads_usage,
  1 AS execution_count,
  ql.current_database AS current_database,
  if(ql.is_initial_query, ql.query, '') AS query,
  if(ql.is_initial_query, ql.normalized_query_hash, 0) AS normalized_query_hash,
  tuple(ql.is_initial_query, ql.query_kind) AS query_kind_by_root,
  if(ql.is_initial_query, ql.tables, []) AS tables,
  if(ql.is_initial_query, ql.exception_code, 0) AS exception_code,
  if(ql.is_initial_query, ql.exception, '') AS exception,
  if(ql.is_initial_query, ql.stack_trace, '') AS stack_trace,
  if(ql.is_initial_query, ql.ProfileEvents['SelectedRows'], 0) AS ProfileEvents_SelectedRows,
  if(ql.is_initial_query, ql.ProfileEvents['SelectedBytes'], 0) AS ProfileEvents_SelectedBytes,
  ql.ProfileEvents['RealTimeMicroseconds'] AS ProfileEvents_RealTimeMicroseconds,
  ql.ProfileEvents['OSCPUVirtualTimeMicroseconds'] AS ProfileEvents_OSCPUVirtualTimeMicroseconds,
  ql.ProfileEvents['UserTimeMicroseconds'] AS ProfileEvents_UserTimeMicroseconds,
  ql.ProfileEvents['SystemTimeMicroseconds'] AS ProfileEvents_SystemTimeMicroseconds,
  ql.ProfileEvents['SelectedParts'] AS ProfileEvents_SelectedParts,
  ql.ProfileEvents['SelectedMarks'] AS ProfileEvents_SelectedMarks,
  ql.ProfileEvents['NetworkReceiveBytes'] AS ProfileEvents_NetworkReceiveBytes,
  ql.ProfileEvents['NetworkSendBytes'] AS ProfileEvents_NetworkSendBytes,
  ql.ProfileEvents['ReadBufferFromFileDescriptorReadBytes'] AS ProfileEvents_ReadBufferFromFileDescriptorReadBytes,
  ql.ProfileEvents['WriteBufferFromFileDescriptorWriteBytes'] AS ProfileEvents_WriteBufferFromFileDescriptorWriteBytes,
  ql.ProfileEvents['S3Clients'] AS ProfileEvents_S3Clients,
  ql.ProfileEvents['S3DeleteObjects'] AS ProfileEvents_S3DeleteObjects,
  ql.ProfileEvents['S3CopyObject'] AS ProfileEvents_S3CopyObject,
  ql.ProfileEvents['S3ListObjects'] AS ProfileEvents_S3ListObjects,
  ql.ProfileEvents['S3HeadObject'] AS ProfileEvents_S3HeadObject,
  ql.ProfileEvents['S3GetObjectAttributes'] AS ProfileEvents_S3GetObjectAttributes,
  ql.ProfileEvents['S3CreateMultipartUpload'] AS ProfileEvents_S3CreateMultipartUpload,
  ql.ProfileEvents['S3UploadPartCopy'] AS ProfileEvents_S3UploadPartCopy,
  ql.ProfileEvents['S3UploadPart'] AS ProfileEvents_S3UploadPart,
  ql.ProfileEvents['S3AbortMultipartUpload'] AS ProfileEvents_S3AbortMultipartUpload,
  ql.ProfileEvents['S3CompleteMultipartUpload'] AS ProfileEvents_S3CompleteMultipartUpload,
  ql.ProfileEvents['S3PutObject'] AS ProfileEvents_S3PutObject,
  ql.ProfileEvents['S3GetObject'] AS ProfileEvents_S3GetObject,
  ql.ProfileEvents['ReadBufferFromS3Bytes'] AS ProfileEvents_ReadBufferFromS3Bytes,
  ql.ProfileEvents['WriteBufferFromS3Bytes'] AS ProfileEvents_WriteBufferFromS3Bytes,
  lc.org_id AS lc_org_id,
  lc.user_id AS lc_user_id,
  lc.session_id AS lc_session_id,
  lc.is_impersonated AS lc_is_impersonated,
  lc.workflow AS lc_workflow,
  lc.kind AS lc_kind,
  lc.id AS lc_id,
  lc.route_id AS lc_route_id,
  lc.access_method AS lc_access_method,
  lc.api_key_label AS lc_api_key_label,
  lc.api_key_mask AS lc_api_key_mask,
  lc.query_type AS lc_query_type,
  lc.product AS lc_product,
  lc.chargeable AS lc_chargeable,
  lc.name AS lc_name,
  lc.request_name AS lc_request_name,
  lc.client_query_id AS lc_client_query_id,
  lc.dashboard_id AS lc_dashboard_id,
  lc.insight_id AS lc_insight_id,
  lc.cohort_id AS lc_cohort_id,
  lc.batch_export_id AS lc_batch_export_id,
  lc.experiment_id AS lc_experiment_id,
  lc.experiment_feature_flag_key AS lc_experiment_feature_flag_key,
  lc.alert_config_id AS lc_alert_config_id,
  lc.feature AS lc_feature,
  lc.table_id AS lc_table_id,
  lc.warehouse_query AS lc_warehouse_query,
  lc.person_on_events_mode AS lc_person_on_events_mode,
  lc.service_name AS lc_service_name,
  lc.workload AS lc_workload,
  if(notEmpty(lc.query.source.kind), lc.query.source.kind, lc.query.kind) AS lc_query__kind,
  if(
    ql.is_initial_query,
    if(notEmpty(lc.query.source.kind), lc.query.source.query, lc.query.query),
    ''
  ) AS lc_query__query,
  if(ql.is_initial_query, JSONExtractRaw(ql.log_comment, 'query'), '') AS lc_query,
  if(ql.is_initial_query, JSONExtractRaw(ql.log_comment, 'modifiers'), '') AS lc_modifiers,
  lc.temporal.workflow_namespace AS lc_temporal__workflow_namespace,
  lc.temporal.workflow_type AS lc_temporal__workflow_type,
  lc.temporal.workflow_id AS lc_temporal__workflow_id,
  lc.temporal.workflow_run_id AS lc_temporal__workflow_run_id,
  lc.temporal.activity_type AS lc_temporal__activity_type,
  lc.temporal.activity_id AS lc_temporal__activity_id,
  lc.temporal.attempt AS lc_temporal__attempt,
  lc.dagster.job_name AS lc_dagster__job_name,
  lc.dagster.run_id AS lc_dagster__run_id,
  lc.dagster.tags.owner AS lc_dagster__owner,
  lc.experiment_name AS lc_experiment_name,
  lc.experiment_metric_name AS lc_experiment_metric_name,
  lc.experiment_execution_path AS lc_experiment_execution_path,
  lc.experiment_metric_type AS lc_experiment_metric_type,
  lc.experiment_funnel_order_type AS lc_experiment_funnel_order_type,
  lc.experiment_exposures_path AS lc_experiment_exposures_path,
  lc.experiment_metric_events_path AS lc_experiment_metric_events_path,
  lc.experiment_query_surface AS lc_experiment_query_surface,
  lc.experiment_precompute_table AS lc_experiment_precompute_table,
  lc.experiment_query_group_id AS lc_experiment_query_group_id,
  lc.experiment_precompute_skip_reason AS lc_experiment_precompute_skip_reason,
  lc.experiment_scan_date_from AS lc_experiment_scan_date_from,
  lc.experiment_scan_date_to AS lc_experiment_scan_date_to,
  lc.precompute_window_start AS lc_precompute_window_start,
  lc.precompute_window_end AS lc_precompute_window_end,
  lc.plan_fingerprint AS lc_plan_fingerprint,
  lc.estimated_rows AS lc_estimated_rows,
  lc.estimated_bytes AS lc_estimated_bytes
FROM system.query_log AS ql
WHERE ql.type != 'QueryStart';
CREATE VIEW posthog.custom_metrics_backups AS WITH
  ['ClickHouseCustomMetric_BackupFailed', 'ClickHouseCustomMetric_BackupSuccess', 'ClickHouseCustomMetric_BackupCancelled', 'ClickHouseCustomMetric_BackupAttempts'] AS names,
  [toInt64(countIf(status = 'BACKUP_FAILED')), toInt64(countIf(status = 'BACKUP_CREATED')), toInt64(countIf(status = 'BACKUP_CANCELLED')), toInt64(countIf(status = 'CREATING_BACKUP'))] AS `values`,
  ['Number of failed backups', 'Number of successful backups', 'Number of cancelled backups', 'Number of backup attempts'] AS descriptions,
  ['gauge', 'gauge', 'gauge', 'gauge'] AS types,
  arrayJoin(arrayZip(names, `values`, descriptions, types)) AS tpl
SELECT
  tpl.1 AS name,
  map('instance', hostname()) AS labels,
  tpl.2 AS value,
  tpl.3 AS help,
  tpl.4 AS type
FROM system.backup_log
WHERE event_date = today()
GROUP BY
  event_date;
CREATE VIEW posthog.custom_metrics_dictionaries AS SELECT
  'ClickHouseCustomMetric_DictionariesFailed' AS name,
  map(
    'instance',
    hostname(),
    'database',
    d.database,
    'dictionary',
    d.dict_name,
    'uuid',
    toString(d.uuid),
    'status',
    toString(d.status)
  ) AS labels,
  toUInt64(1) AS value,
  'Dictionary is in FAILED or FAILED_AND_RELOADING status' AS help,
  'gauge' AS type
FROM
  (
    SELECT name AS dict_name, database, uuid, status
    FROM system.dictionaries
    WHERE status IN ('FAILED', 'FAILED_AND_RELOADING')
  ) AS d;
CREATE VIEW posthog.custom_metrics_part_counts AS SELECT
  'ClickHouseCustomMetric_MaxPartCountPerPartition' AS name,
  map('instance', hostname(), 'database', database, 'table', `table`, 'partition', partition) AS labels,
  part_count AS value,
  'Maximum number of active parts for any partition in a PostHog table' AS help,
  'gauge' AS type
FROM
  (
    SELECT database, `table`, partition, count() AS part_count
    FROM system.parts
    WHERE
      active
    AND
      (database = 'posthog')
    GROUP BY
      database, `table`, partition
    ORDER BY database ASC, `table` ASC, part_count DESC, partition ASC
    LIMIT 1 BY database, `table`
  );
CREATE VIEW posthog.custom_metrics_replication_queue AS WITH
  ['ClickHouseCustomMetric_ReplicationQueueStuckEntries', 'ClickHouseCustomMetric_ReplicationQueueMaxPostponedEntrySeconds', 'ClickHouseCustomMetric_ReplicationQueueMaxErrorEntrySeconds'] AS names,
  [toInt64(countIf(create_time < (now() - toIntervalDay(15)))), maxIf(dateDiff('seconds', create_time, last_postpone_time), last_postpone_time != '1970-01-01'), maxIf(dateDiff('seconds', create_time, last_exception_time), (last_exception_time != '1970-01-01') AND (last_exception_time > (now() - toIntervalMinute(5))))] AS `values`,
  ['Number of entries that have been in the replication queue for more than 15 days', 'Maximum number of seconds that an entry has been postponed', 'Maximum number of seconds that an entry has been in error'] AS descriptions,
  ['gauge', 'gauge', 'gauge'] AS types,
  arrayJoin(arrayZip(names, `values`, descriptions, types)) AS tpl
SELECT
  tpl.1 AS name,
  map('table', `table`, 'instance', hostname()) AS labels,
  tpl.2 AS value,
  tpl.3 AS help,
  tpl.4 AS type
FROM system.replication_queue
GROUP BY
  `table`
HAVING
  value > 0;
CREATE VIEW posthog.custom_metrics_server_crash AS SELECT
  'ClickHouseCustomMetric_ServerCrash' AS name,
  map('instance', hostname()) AS labels,
  count() AS value,
  'Number of server crashes for current date' AS help,
  'gauge' AS type
FROM system.crash_log
WHERE event_date = today()
GROUP BY
  hostname();
CREATE VIEW posthog.custom_metrics_table_sizes AS SELECT
  'ClickHouseCustomMetric_TableTotalBytes' AS name,
  map('instance', hostname(), 'database', database, 'table', `table`) AS labels,
  CAST(total_bytes, 'Float64') AS value,
  'Size of a database table on a given node (need a sum for sharded)' AS help,
  'gauge' AS type
FROM system.tables
WHERE
  (database NOT IN ('INFORMATION_SCHEMA', 'information_schema'))
AND
  (total_bytes IS NOT NULL);
CREATE VIEW posthog.custom_metrics_test AS SELECT
  'ClickHouseCustomMetric_Test' AS name,
  map('instance', hostname()) AS labels,
  1 AS value,
  'Test to check that the metric endpoint is working' AS help,
  'gauge' AS type;
CREATE OR REPLACE DICTIONARY posthog.channel_definition_dict (`domain` String, `kind` String, `domain_type` Nullable(String), `type_if_paid` Nullable(String), `type_if_organic` Nullable(String)) PRIMARY KEY domain, kind SOURCE(CLICKHOUSE(USER 'dict_reader' TABLE 'channel_definition')) LAYOUT(COMPLEX_KEY_HASHED()) LIFETIME(MIN 3000 MAX 3600);
CREATE OR REPLACE DICTIONARY posthog.web_pre_aggregated_teams_dict (`team_id` UInt64) PRIMARY KEY team_id SOURCE(CLICKHOUSE(USER 'dict_reader' QUERY 'SELECT     team_id FROM     `web_pre_aggregated_teams` FINAL WHERE version > 0')) LAYOUT(HASHED()) LIFETIME(MIN 3000 MAX 3600);
CREATE VIEW posthog.custom_metrics AS SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_test
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_replication_queue
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_server_crash
UNION ALL
SELECT *
FROM posthog.custom_metrics_table_sizes
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_part_counts
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_dictionaries
UNION ALL
SELECT
  'ClickHouseCustomMetric_S3DiskBytesUsed' AS name,
  map('instance', hostname(), 'disk', disk_name) AS labels,
  toFloat64(sum(bytes_on_disk)) AS value,
  'Bytes currently used by ClickHouse parts on S3-backed disks on this node' AS help,
  'gauge' AS type
FROM system.parts
WHERE disk_name IN ('s3disk', 'cache')
GROUP BY
  disk_name
UNION ALL
SELECT
  'ClickHouseCustomMetric_MergeFailures15m' AS name,
  map('instance', hostname()) AS labels,
  toFloat64(count()) AS value,
  'Number of failed merge operations in the last 15 minutes' AS help,
  'gauge' AS type
FROM system.part_log
WHERE
  (event_time >= (now() - toIntervalMinute(15)))
AND
  (event_type = 'MergeParts')
AND
  (error > 0)
AND
  (merge_reason != 'NotAMerge')
AND
  (error != 40)
UNION ALL
SELECT
  'ClickHouseCustomMetric_MergeRetriesMaxPerTable15m' AS name,
  map('instance', hostname()) AS labels,
  toFloat64(max(cnt)) AS value,
  'Max failed merge retries for any single table in the last 15 minutes' AS help,
  'gauge' AS type
FROM
  (
    SELECT count() AS cnt
    FROM system.part_log
    WHERE
      (event_time >= (now() - toIntervalMinute(15)))
    AND
      (event_type = 'MergeParts')
    AND
      (error > 0)
    AND
      (merge_reason != 'NotAMerge')
    AND
      (error != 40)
    GROUP BY
      database, `table`, partition_id
  );

# prod-us data cluster: objects only prod-us runs, and the deltas it applies to the cloud shape.
database "posthog" {

  table "asyncdeletion_join" {
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
    engine "join" {
      strictness = "ANY"
      type       = "LEFT"
      keys       = ["team_id", "key"]
    }
  }

  table "distributed_person" {
    column "id" {
      type = "UUID"
    }
    column "created_at" {
      type = "DateTime"
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_person"
      sharding_key    = "sipHash64(id)"
    }
  }

  table "distributed_person_distinct_id" {
    column "id" {
      type = "Int64"
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
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_person_distinct_id"
      sharding_key    = "sipHash64(distinct_id)"
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
      type = "DateTime"
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
    column "is_deleted" {
      type    = "Int8"
      default = "0"
    }
    column "version" {
      type = "UInt64"
    }
    column "_partition" {
      type = "UInt32"
    }
    column "last_seen_at" {
      type = "Nullable(DateTime64(3))"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/am0005_20220623103132_noshard/posthog.person"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  table "person_distinct_id_overrides_join_table" {
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    engine "join" {
      strictness = "ANY"
      type       = "LEFT"
      keys       = ["team_id", "distinct_id"]
    }
  }

  table "person_distinct_id_overrides_to_delete" {
    order_by = ["team_id", "distinct_id"]
    settings = {
      default_compression_codec = "lz4"
      index_granularity         = "512"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "version" {
      type = "Int64"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.person_distinct_id_overrides_to_delete"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  table "person_distinct_id_overrides_to_delete_join" {
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "version" {
      type = "Int64"
    }
    engine "join" {
      strictness = "ANY"
      type       = "LEFT"
      keys       = ["team_id", "distinct_id"]
    }
  }

  table "person_overrides_join_table" {
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    engine "join" {
      strictness = "ANY"
      type       = "LEFT"
      keys       = ["team_id", "distinct_id"]
    }
  }

  table "sharded_events" {
    override = true
    order_by     = ["team_id", "toDate(timestamp)", "event", "cityHash64(distinct_id)", "cityHash64(uuid)"]
    partition_by = "toYYYYMM(timestamp)"
    sample_by    = "cityHash64(distinct_id)"
    settings = {
      index_granularity                    = "8192"
      max_avg_part_size_for_too_many_parts = "0"
    }
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type  = "String"
      codec = "Default"
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
    column "$group_0" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), concat('^[', regexpQuoteMeta('\"'), ']*|[', regexpQuoteMeta('\"'), ']*$'), '')"
    }
    column "$group_1" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_1'), concat('^[', regexpQuoteMeta('\"'), ']*|[', regexpQuoteMeta('\"'), ']*$'), '')"
    }
    column "$group_2" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_2'), concat('^[', regexpQuoteMeta('\"'), ']*|[', regexpQuoteMeta('\"'), ']*$'), '')"
    }
    column "$group_3" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_3'), concat('^[', regexpQuoteMeta('\"'), ']*|[', regexpQuoteMeta('\"'), ']*$'), '')"
    }
    column "$group_4" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_4'), concat('^[', regexpQuoteMeta('\"'), ']*|[', regexpQuoteMeta('\"'), ']*$'), '')"
    }
    column "$window_id" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$window_id'), concat('^[', regexpQuoteMeta('\"'), ']*|[', regexpQuoteMeta('\"'), ']*$'), '')"
    }
    column "$session_id" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$session_id'), concat('^[', regexpQuoteMeta('\"'), ']*|[', regexpQuoteMeta('\"'), ']*$'), '')"
    }
    column "person_id" {
      type = "UUID"
    }
    column "person_properties" {
      type  = "String"
      codec = "Default"
    }
    column "group0_properties" {
      type  = "String"
      codec = "Default"
    }
    column "group1_properties" {
      type  = "String"
      codec = "Default"
    }
    column "group2_properties" {
      type  = "String"
      codec = "Default"
    }
    column "group3_properties" {
      type  = "String"
      codec = "Default"
    }
    column "group4_properties" {
      type  = "String"
      codec = "Default"
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
    column "inserted_at" {
      type    = "Nullable(DateTime64(6, 'UTC'))"
      default = "now64()"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "elements_chain_href" {
      type         = "String"
      materialized = "EXTRACT(elements_chain, '(?::|\")href=\"(.*?)\"')"
    }
    column "elements_chain_texts" {
      type         = "Array(String)"
      materialized = "arrayDistinct(extractAll(elements_chain, '(?::|\")text=\"(.*?)\"'))"
    }
    column "elements_chain_elements" {
      type         = "Array(Enum8('a'=1, 'button'=2, 'form'=3, 'input'=4, 'select'=5, 'textarea'=6, 'label'=7))"
      materialized = "arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\\\.|$|:)'))"
    }
    column "elements_chain_ids" {
      type         = "Array(String)"
      materialized = "arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id=\"(.*?)\"'))"
    }
    column "properties_group_custom" {
      type         = "Map(String, String)"
      materialized = "mapSort(mapFilter((key, _) -> ((key NOT LIKE '$%') AND (key NOT IN ('token', 'distinct_id', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'gad_source', 'gclsrc', 'dclid', 'gbraid', 'wbraid', 'fbclid', 'msclkid', 'twclid', 'li_fat_id', 'mc_cid', 'igshid', 'ttclid', 'rdt_cid'))), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))"
      codec        = "Default"
    }
    column "properties_group_feature_flags" {
      type         = "Map(String, String)"
      materialized = "mapSort(mapFilter((key, _) -> (key LIKE '$feature/%'), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))"
      codec        = "Default"
    }
    column "is_deleted" {
      type = "Bool"
    }
    column "person_properties_map_custom" {
      type         = "Map(String, String)"
      materialized = "mapSort(mapFilter((key, _) -> (key NOT LIKE '$%'), CAST(JSONExtractKeysAndValues(person_properties, 'String'), 'Map(String, String)')))"
      codec        = "Default"
    }
    column "mat_$ai_trace_id" {
      type    = "Nullable(String)"
      default = "JSONExtract(properties, '$ai_trace_id', 'Nullable(String)')"
    }
    column "$session_id_uuid" {
      type         = "Nullable(UInt128)"
      materialized = "toUInt128(JSONExtract(properties, '$session_id', 'Nullable(UUID)'))"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
    column "properties_map_ephemeral" {
      type = "Map(String, String)"
    }
    column "person_properties_map_ephemeral" {
      type = "Map(String, String)"
    }
    column "properties_group_ai" {
      type         = "Map(String, String)"
      materialized = "mapSort(mapFilter((key, _) -> ((key LIKE '$ai_%') AND (key NOT IN ('$ai_input', '$ai_input_state', '$ai_output', '$ai_output_choices', '$ai_output_state', '$ai_tools'))), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))"
      codec        = "Default"
    }
    column "mat_historical_migration" {
      type    = "Nullable(String)"
      default = "JSONExtract(properties, 'historical_migration', 'Nullable(String)')"
    }
    column "mat_$ai_session_id" {
      type         = "Nullable(String)"
      materialized = "JSONExtract(properties, '$ai_session_id', 'Nullable(String)')"
    }
    column "mat_$ai_is_error" {
      type         = "Nullable(String)"
      materialized = "JSONExtract(properties, '$ai_is_error', 'Nullable(String)')"
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
    column "historical_migration" {
      type = "Bool"
    }
    column "mat_$ai_prompt_name" {
      type         = "Nullable(String)"
      materialized = "JSONExtract(properties, '$ai_prompt_name', 'Nullable(String)')"
    }
    column "mat_$ai_experiment_id" {
      type         = "Nullable(String)"
      materialized = "JSONExtract(properties, '$ai_experiment_id', 'Nullable(String)')"
    }
    index "kafka_timestamp_minmax_sharded_events" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    index "minmax_$group_0" {
      expr        = "`$group_0`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$group_1" {
      expr        = "`$group_1`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$group_2" {
      expr        = "`$group_2`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$group_3" {
      expr        = "`$group_3`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$group_4" {
      expr        = "`$group_4`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$window_id" {
      expr        = "`$window_id`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$session_id" {
      expr        = "`$session_id`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_inserted_at" {
      expr        = "coalesce(inserted_at, _timestamp)"
      type        = "minmax"
      granularity = 1
    }
    index "properties_group_custom_keys_bf" {
      expr        = "mapKeys(properties_group_custom)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "properties_group_custom_values_bf" {
      expr        = "mapValues(properties_group_custom)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "properties_group_feature_flags_keys_bf" {
      expr        = "mapKeys(properties_group_feature_flags)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "properties_group_feature_flags_values_bf" {
      expr        = "mapValues(properties_group_feature_flags)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "is_deleted_idx" {
      expr        = "is_deleted"
      type        = "minmax"
      granularity = 1
    }
    index "person_properties_map_custom_keys_bf" {
      expr        = "mapKeys(person_properties_map_custom)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "person_properties_map_custom_values_bf" {
      expr        = "mapValues(person_properties_map_custom)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_mat_$ai_trace_id" {
      expr        = "`mat_$ai_trace_id`"
      type        = "minmax"
      granularity = 1
    }
    index "properties_group_ai_keys_bf" {
      expr        = "mapKeys(properties_group_ai)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "properties_group_ai_values_bf" {
      expr        = "mapValues(properties_group_ai)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "bloom_filter_$ai_trace_id" {
      expr        = "`mat_$ai_trace_id`"
      type        = "bloom_filter(0.001)"
      granularity = 2
    }
    index "minmax_mat_historical_migration" {
      expr        = "mat_historical_migration"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_filter_$ai_session_id" {
      expr        = "`mat_$ai_session_id`"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_$ai_session_id" {
      expr        = "`mat_$ai_session_id`"
      type        = "minmax"
      granularity = 1
    }
    index "set_$ai_is_error" {
      expr        = "`mat_$ai_is_error`"
      type        = "set(7)"
      granularity = 1
    }
    index "bloom_filter_distinct_id" {
      expr        = "distinct_id"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_sharded_events_timestamp" {
      expr        = "timestamp"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_historical_migration" {
      expr        = "historical_migration"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_filter_$ai_prompt_name" {
      expr        = "`mat_$ai_prompt_name`"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_$ai_prompt_name" {
      expr        = "`mat_$ai_prompt_name`"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_filter_$ai_experiment_id" {
      expr        = "`mat_$ai_experiment_id`"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_$ai_experiment_id" {
      expr        = "`mat_$ai_experiment_id`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$session_id_uuid" {
      expr        = "`$session_id_uuid`"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_filter_$session_id" {
      expr        = "nullIf(nullIf(`$session_id`, ''), 'null')"
      type        = "bloom_filter"
      granularity = 1
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/reshard3/{shard}/posthog.sharded_events"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }

  table "sharded_person" {
    order_by = ["team_id", "id"]
    settings = {
      index_granularity = "8192"
    }
    column "id" {
      type = "UUID"
    }
    column "created_at" {
      type = "DateTime"
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/reshard/{shard}/posthog.sharded_person"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }

  table "sharded_person_distinct_id" {
    order_by = ["team_id", "distinct_id", "person_id"]
    settings = {
      index_granularity = "8192"
    }
    column "id" {
      type = "Int64"
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
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/reshard/{shard}/posthog.sharded_person_distinct_id"
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
      zoo_path     = "/clickhouse/tables/reshard/{shard}/posthog.raw_sessions_v3"
      replica_name = "{replica}"
    }
  }

  table "writable_ingestion_warnings" {
    # The ingestion nodes declare this name too, for the table they write through.
    # A data node holds a different object under it, so this restates rather than
    # redeclares.
    override = true
    column "team_id" {
      type = "Int64"
    }
    column "source" {
      type = "LowCardinality(String)"
    }
    column "type" {
      type = "String"
    }
    column "details" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
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
      remote_table    = "sharded_ingestion_warnings"
      sharding_key    = "rand()"
    }
  }

  table "writable_posthog_document_embeddings" {
    # The ingestion nodes declare this name too, for the table they write through.
    # A data node holds a different object under it, so this restates rather than
    # redeclares.
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

  table "writable_raw_sessions_primary" {
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

  table "writable_sessions_background" {
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_sessions"
      sharding_key    = "sipHash64(session_id)"
    }
  }

  view "events_with_array_props_view" {
    query = <<SQL
SELECT
  uuid,
  event,
  properties,
  timestamp,
  team_id,
  distinct_id,
  elements_chain,
  created_at,
  arrayMap(k -> toString(k.1), JSONExtractKeysAndValuesRaw(properties)) AS array_property_keys,
  arrayMap(k -> toString(k.2), JSONExtractKeysAndValuesRaw(properties)) AS array_property_values,
  _timestamp,
  _offset
FROM posthog.events
SQL

  }

  view "persons_properties_up_to_date_view" {
    query = <<SQL
SELECT *
FROM posthog.persons_properties_view
WHERE
  (id, created_at)
  IN (SELECT id, maxMerge(updated_at) AS latest FROM posthog.persons_up_to_date GROUP BY id)
SQL

  }

  view "persons_up_to_date_view" {
    query = <<SQL
SELECT
  id,
  minMerge(created_at_) AS created_at,
  argMaxMerge(team_id) AS team_id,
  argMaxMerge(properties) AS properties,
  argMaxMerge(is_identified) AS is_identified,
  maxMerge(updated_at) AS updated_at
FROM posthog.persons_up_to_date
GROUP BY
  id
SQL

  }

  view "team_events_last_month_view" {
    query = <<SQL
SELECT team_id, count() AS event_count
FROM posthog.events
WHERE
  (timestamp > (now() - toIntervalMonth(1)))
AND
  (timestamp < now())
GROUP BY
  team_id
ORDER BY event_count DESC
SQL

  }

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
    column "group_0" {
      type  = "String"
      alias = "`$group_0`"
      after = "$session_id"
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
    column "person_id" {
      type  = "UUID"
      after = "group_4"
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

  patch_table "adhoc_events_deletion" {
    settings = {
      default_compression_codec = "lz4"
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

  patch_table "channel_definition" {
    settings = {
      default_compression_codec = "lz4"
    }
  }

  patch_table "cohort_membership" {
    settings = {
      default_compression_codec = "lz4"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/prod/tables/posthog.cohort_membership"
      replica_name   = "{replica}-{shard}"
      version_column = "last_updated"
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

  patch_table "duplicate_events" {
    settings = {
      default_compression_codec = "lz4"
    }
  }

  patch_table "error_tracking_issue_fingerprint_overrides" {
    settings = {
      default_compression_codec = "lz4"
    }
  }

  patch_table "events_dead_letter_queue" {
    settings = {
      default_compression_codec = "lz4"
    }
    index "kafka_timestamp_minmax" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
      first       = true
    }
    index "kafka_timestamp_minmax_events_dead_letter_queue" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.new_events_dead_letter_queue_2"
      replica_name   = "{replica}-{shard}"
      version_column = "_timestamp"
    }
  }

  patch_table "exchange_rate" {
    settings = {
      default_compression_codec = "lz4"
    }
  }

  patch_table "ingestion_warnings" {
    modify_column "details" {
      type  = "String"
      codec = "ZSTD(3)"
    }
  }

  patch_table "llma_metrics_daily" {
    settings = {
      default_compression_codec = "lz4"
    }
  }

  patch_table "person_distinct_id" {
    settings = {
      default_compression_codec = "lz4"
    }
    engine "replicated_collapsing_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.person_distinct_id-swap2-2021-08-18"
      replica_name = "{replica}-{shard}"
      sign_column  = "_sign"
    }
  }

  patch_table "person_distinct_id_overrides" {
    settings = {
      default_compression_codec = "lz4"
    }
  }

  patch_table "person_overrides" {
    settings = {
      default_compression_codec = "lz4"
    }
  }

  patch_table "person_static_cohort" {
    settings = {
      default_compression_codec = "lz4"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/prod/tables/noshard/person_static_cohort"
      replica_name   = "{replica}-{shard}"
      version_column = "_timestamp"
    }
  }

  patch_table "pg_embeddings" {
    settings = {
      default_compression_codec = "lz4"
    }
  }

  patch_table "plugin_log_entries" {
    order_by     = ["team_id", "plugin_id", "plugin_config_id", "timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    settings = {
      default_compression_codec = "lz4"
    }
  }

  patch_table "property_definitions" {
    settings = {
      always_fetch_merged_part     = "0"
      default_compression_codec    = "lz4"
      replicated_can_become_leader = "1"
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

  patch_table "sessions" {
    engine "distributed" {
      cluster_name    = "sessions"
      remote_database = "posthog"
      remote_table    = "sessions"
      sharding_key    = "sipHash64(session_id)"
    }
  }

  patch_table "sharded_app_metrics2" {
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/reshard/{shard}/posthog.sharded_app_metrics2"
      replica_name = "{replica}"
    }
  }

  patch_table "sharded_heatmaps" {
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/reshard/{shard}/posthog.heatmaps"
      replica_name = "{replica}"
    }
  }

  patch_table "sharded_log_entries" {
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/reshard/{shard}/posthog.sharded_log_entries"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }

  patch_table "sharded_performance_events" {
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/reshard/{shard}/posthog.performance_events"
      replica_name = "{replica}"
    }
  }

  patch_table "sharded_posthog_document_embeddings_buffer" {
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/reshard/{shard}/posthog.sharded_posthog_document_embeddings_buffer"
      replica_name   = "{replica}"
      version_column = "inserted_at"
    }
  }

  patch_table "sharded_posthog_document_embeddings_text_embedding_3_large_3072" {
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/reshard/{shard}/posthog.sharded_posthog_document_embeddings_text_embedding_3_large_3072"
      replica_name   = "{replica}"
      version_column = "inserted_at"
    }
  }

  patch_table "sharded_posthog_document_embeddings_text_embedding_3_small_1536" {
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/reshard/{shard}/posthog.sharded_posthog_document_embeddings_text_embedding_3_small_1536"
      replica_name   = "{replica}"
      version_column = "inserted_at"
    }
  }

  patch_table "sharded_preaggregation_results" {
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/reshard/{shard}/posthog.preaggregation_results"
      replica_name = "{replica}"
    }
  }

  patch_table "sharded_session_replay_embeddings" {
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/reshard/{shard}/posthog.session_replay_embeddings"
      replica_name = "{replica}"
    }
  }

  patch_table "sharded_session_replay_events" {
    modify_column "snapshot_source" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/reshard/{shard}/posthog.session_replay_events"
      replica_name = "{replica}"
    }
  }

  patch_table "web_pre_aggregated_bounces" {
    settings = {
      default_compression_codec = "lz4"
    }
  }

  patch_table "web_pre_aggregated_stats" {
    settings = {
      default_compression_codec = "lz4"
    }
  }

  patch_table "web_pre_aggregated_teams" {
    settings = {
      default_compression_codec = "lz4"
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
    engine "distributed" {
      cluster_name    = "posthog_writable"
      remote_database = "posthog"
      remote_table    = "sharded_session_replay_events"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }

  patch_table "writable_sessions" {
    engine "distributed" {
      cluster_name    = "posthog_writable"
      remote_database = "posthog"
      remote_table    = "sharded_sessions"
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

  table "clickhouse_cleanup_deleted_persons" {
    override = true
    order_by     = ["run_id", "team_id", "person_id"]
    partition_by = "run_id"
    ttl          = "created_at + toIntervalDay(14)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    column "run_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "person_id" {
      type = "UUID"
    }
    column "max_version" {
      type = "UInt64"
    }
    column "created_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.clickhouse_cleanup_deleted_persons"
      replica_name   = "{replica}-{shard}"
      version_column = "created_at"
    }
  }

  table "clickhouse_cleanup_orphaned_distinct_ids" {
    override = true
    order_by     = ["run_id", "team_id", "distinct_id"]
    partition_by = "run_id"
    ttl          = "created_at + toIntervalDay(14)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    column "run_id" {
      type = "String"
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
    column "own_tombstone" {
      type = "UInt8"
    }
    column "max_version" {
      type = "Int64"
    }
    column "created_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.clickhouse_cleanup_orphaned_distinct_ids"
      replica_name   = "{replica}-{shard}"
      version_column = "created_at"
    }
  }

  table "clickhouse_cleanup_revived_distinct_ids" {
    override = true
    order_by     = ["run_id", "team_id", "distinct_id"]
    partition_by = "run_id"
    ttl          = "created_at + toIntervalDay(14)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    column "run_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "created_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.clickhouse_cleanup_revived_distinct_ids"
      replica_name   = "{replica}-{shard}"
      version_column = "created_at"
    }
  }

  table "clickhouse_cleanup_revived_persons" {
    override = true
    order_by     = ["run_id", "team_id", "person_id"]
    partition_by = "run_id"
    ttl          = "created_at + toIntervalDay(14)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    column "run_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "person_id" {
      type = "UUID"
    }
    column "created_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.clickhouse_cleanup_revived_persons"
      replica_name   = "{replica}-{shard}"
      version_column = "created_at"
    }
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

  table "groups" {
    override = true
    order_by = ["team_id", "group_type_index", "group_key"]
    settings = {
      index_granularity = "8192"
    }
    column "group_type_index" {
      type = "UInt8"
    }
    column "group_key" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(3)"
    }
    column "team_id" {
      type = "Int64"
    }
    column "group_properties" {
      type = "String"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "is_deleted" {
      type = "Bool"
    }
    index "is_deleted_idx" {
      expr        = "is_deleted"
      type        = "minmax"
      granularity = 1
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.groups"
      replica_name   = "{replica}-{shard}"
      version_column = "_timestamp"
    }
  }

  view "persons_batch_export" {
    override = true
    query = <<SQL
WITH
  new_persons AS (SELECT id, max(version) AS version, argMax(_timestamp, person.version) AS _timestamp2 FROM posthog.person WHERE (team_id = {team_id: Int64}) AND (id IN (SELECT id FROM posthog.person WHERE (team_id = {team_id: Int64}) AND (_timestamp >= {interval_start: DateTime64}) AND (_timestamp < {interval_end: DateTime64}))) GROUP BY id HAVING (_timestamp2 >= {interval_start: DateTime64}) AND (_timestamp2 < {interval_end: DateTime64})),
  new_distinct_ids AS (SELECT argMax(person_id, person_distinct_id2.version) AS person_id FROM posthog.person_distinct_id2 WHERE (team_id = {team_id: Int64}) AND (distinct_id IN (SELECT distinct_id FROM posthog.person_distinct_id2 WHERE (team_id = {team_id: Int64}) AND (_timestamp >= {interval_start: DateTime64}) AND (_timestamp < {interval_end: DateTime64}))) GROUP BY distinct_id HAVING (argMax(_timestamp, person_distinct_id2.version) >= {interval_start: DateTime64}) AND (argMax(_timestamp, person_distinct_id2.version) < {interval_end: DateTime64})),
  all_new_persons AS (SELECT id, version FROM new_persons UNION ALL SELECT id, max(version) FROM posthog.person WHERE (team_id = {team_id: Int64}) AND (id IN (new_distinct_ids)) GROUP BY id)
SELECT
  p.team_id AS team_id,
  pd.distinct_id AS distinct_id,
  toString(p.id) AS person_id,
  p.properties AS properties,
  pd.version AS person_distinct_id_version,
  p.version AS person_version,
  p.created_at AS created_at,
  multiIf(
    ((pd._timestamp >= {interval_start: DateTime64}) AND (pd._timestamp < {interval_end: DateTime64}))
    AND (NOT ((p._timestamp >= {interval_start: DateTime64}) AND (p._timestamp < {interval_end: DateTime64}))),
    pd._timestamp,
    ((p._timestamp >= {interval_start: DateTime64}) AND (p._timestamp < {interval_end: DateTime64}))
    AND (NOT ((pd._timestamp >= {interval_start: DateTime64}) AND (pd._timestamp < {interval_end: DateTime64}))),
    p._timestamp,
    least(p._timestamp, pd._timestamp)
  ) AS _inserted_at
FROM
  posthog.person AS p INNER JOIN (SELECT distinct_id, max(version) AS version, argMax(person_id, person_distinct_id2.version) AS person_id2, argMax(_timestamp, person_distinct_id2.version) AS _timestamp FROM posthog.person_distinct_id2 WHERE (team_id = {team_id: Int64}) AND (person_id IN (SELECT id FROM all_new_persons)) GROUP BY distinct_id) AS pd ON p.id = pd.person_id2
WHERE
  (team_id = {team_id: Int64})
AND
  ((id, version) IN (all_new_persons))
ORDER BY _inserted_at ASC
SQL

  }

  materialized_view "posthog_document_embeddings_text_embedding_3_large_3072_mv" {
    override = true
    to_table = "posthog.writable_posthog_document_embeddings_text_embedding_3_large_3072"
    query    = <<SQL
SELECT
  team_id,
  product,
  document_type,
  rendering,
  document_id,
  timestamp,
  inserted_at,
  content,
  metadata,
  embedding,
  _timestamp,
  _offset,
  _partition
FROM posthog.sharded_posthog_document_embeddings_buffer
WHERE model_name = 'text-embedding-3-large-3072'
SQL

    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
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
      type = "String"
    }
    column "metadata" {
      type = "String"
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
  }

  materialized_view "posthog_document_embeddings_text_embedding_3_small_1536_mv" {
    override = true
    to_table = "posthog.writable_posthog_document_embeddings_text_embedding_3_small_1536"
    query    = <<SQL
SELECT
  team_id,
  product,
  document_type,
  rendering,
  document_id,
  timestamp,
  inserted_at,
  content,
  metadata,
  embedding,
  _timestamp,
  _offset,
  _partition
FROM posthog.sharded_posthog_document_embeddings_buffer
WHERE model_name = 'text-embedding-3-small-1536'
SQL

    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
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
      type = "String"
    }
    column "metadata" {
      type = "String"
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
  }

  table "raw_sessions_v3" {
    override = true
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_raw_sessions_v3"
      sharding_key    = "cityHash64(session_id_v7)"
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

  table "session_replay_events" {
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
    column "min_first_timestamp" {
      type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))"
    }
    column "max_last_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "first_url" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "click_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "keypress_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "mouse_activity_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "active_milliseconds" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "console_log_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "console_warn_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "console_error_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "size" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "message_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "event_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime)"
    }
    column "snapshot_source" {
      type = "AggregateFunction(argMin, LowCardinality(Nullable(String)), DateTime64(6, 'UTC'))"
    }
    column "all_urls" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "snapshot_library" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "block_first_timestamps" {
      type = "SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC')))"
    }
    column "block_last_timestamps" {
      type = "SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC')))"
    }
    column "block_urls" {
      type = "SimpleAggregateFunction(groupArrayArray, Array(String))"
    }
    column "retention_period_days" {
      type = "SimpleAggregateFunction(max, Nullable(Int64))"
    }
    column "is_deleted" {
      type    = "SimpleAggregateFunction(max, UInt8)"
      default = "0"
    }
    column "ai_tags_fixed" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "ai_tags_freeform" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "ai_highlighted" {
      type    = "SimpleAggregateFunction(max, UInt8)"
      default = "0"
    }
    column "surfacing_score" {
      type = "SimpleAggregateFunction(max, Nullable(Float32))"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_session_replay_events"
      sharding_key    = "sipHash64(distinct_id)"
    }
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

  table "tophog" {
    override = true
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "metric" {
      type = "LowCardinality(String)"
    }
    column "type" {
      type    = "LowCardinality(String)"
      default = "'sum'"
    }
    column "key" {
      type = "Map(LowCardinality(String), String)"
    }
    column "value" {
      type = "Float64"
    }
    column "count" {
      type    = "UInt64"
      default = "0"
    }
    column "pipeline" {
      type = "LowCardinality(String)"
    }
    column "lane" {
      type = "LowCardinality(String)"
    }
    column "labels" {
      type = "Map(LowCardinality(String), String)"
    }
    engine "distributed" {
      cluster_name    = "ops"
      remote_database = "posthog"
      remote_table    = "sharded_tophog"
      sharding_key    = "cityHash64(toString(key))"
    }
  }

  table "writable_posthog_document_embeddings_buffer" {
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
    column "metadata" {
      type    = "String"
      default = "'{}'"
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
      remote_table    = "sharded_posthog_document_embeddings_buffer"
      sharding_key    = "cityHash64(document_id)"
    }
  }
}

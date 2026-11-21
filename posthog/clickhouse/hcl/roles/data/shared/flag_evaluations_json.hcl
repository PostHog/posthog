# Native-JSON flag evaluation reads. The column list and the Distributed read table sit in the
# shared layer because every data node has the read table, cloud included. A layer only some
# cloud nodes compose cannot describe it. The storage table is in roles/coshared/flag_evaluations_data.
database "posthog" {
  # The column list of the native-JSON flag evaluation tables. The storage table and the read
  # table extend it. The typed columns (flag_key, response and request_id) carry their DEFAULT
  # expression only on the storage table.
  table "_flag_evaluations_json_columns" {
    abstract = true
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "JSON(`$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$config_defaults` LowCardinality(String), `$current_url` String, `$device_type` LowCardinality(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$host` String, `$lib` LowCardinality(String), `$lib_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String), `$pathname` String, `$session_id` String, `$timezone` LowCardinality(String), `$window_id` String)"
    }
    column "temporary_properties" {
      type = "JSON(max_dynamic_paths=32)"
    }
    column "properties_null_keys" {
      type = "Array(LowCardinality(String))"
    }
    column "temporary_properties_null_keys" {
      type = "Array(LowCardinality(String))"
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
    column "created_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
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
    column "person_id" {
      type = "UUID"
    }
    column "person_properties" {
      type = "JSON(max_dynamic_paths=256, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$device_type` LowCardinality(String), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$initial_browser` LowCardinality(String), `$initial_browser_language` LowCardinality(String), `$initial_browser_version` LowCardinality(String), `$initial_device_type` LowCardinality(String), `$initial_geoip_city_name` LowCardinality(String), `$initial_geoip_continent_code` LowCardinality(String), `$initial_geoip_continent_name` LowCardinality(String), `$initial_geoip_country_code` LowCardinality(String), `$initial_geoip_country_name` LowCardinality(String), `$initial_geoip_subdivision_1_name` LowCardinality(String), `$initial_geoip_time_zone` LowCardinality(String), `$initial_os` LowCardinality(String), `$initial_os_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String))"
    }
    column "person_properties_null_keys" {
      type = "Array(LowCardinality(String))"
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
    column "inserted_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "timestamp"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
    column "historical_migration" {
      type = "Bool"
    }
    column "total_event_size" {
      type = "UInt32"
    }
    column "captured_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "_partition" {
      type = "UInt64"
    }
    column "elements_chain_href" {
      type = "String"
    }
    column "elements_chain_texts" {
      type = "Array(String)"
    }
    column "elements_chain_ids" {
      type = "Array(String)"
    }
    column "elements_chain_elements" {
      type = "Array(Enum8('a'=1, 'button'=2, 'form'=3, 'input'=4, 'select'=5, 'textarea'=6, 'label'=7))"
    }
    column "flag_key" {
      type    = "String"
      comment = "column_materializer::properties::$feature_flag"
    }
    column "response" {
      type    = "LowCardinality(String)"
      comment = "column_materializer::properties::$feature_flag_response"
    }
    column "request_id" {
      type    = "String"
      comment = "column_materializer::temporary_properties::$feature_flag_request_id"
    }
  }

  table "flag_evaluations_json" {
    extend = "_flag_evaluations_json_columns"
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_flag_evaluations_json"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }
}

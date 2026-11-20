# The Kafka consumer for the native-JSON flag evaluations and the MV that feeds it into storage.
# This is the local shape: the MV writes through writable_flag_evaluations_json, which the
# ingestion_medium local layer declares. The flags role patches the MV to write straight into
# sharded_flag_evaluations_json, since its Kafka table and storage share a host.
database "posthog" {
  table "kafka_flag_evaluations_json" {
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "LowCardinality(String)"
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
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "person_id" {
      type = "UUID"
    }
    column "person_properties" {
      type = "String"
    }
    column "person_created_at" {
      type = "DateTime64(3)"
    }
    column "inserted_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    engine "kafka" {
      collection           = "warpstream_ingestion"
      topic_list           = "clickhouse_flag_evaluations"
      group_name           = "clickhouse_flag_evaluations_json"
      format               = "JSONEachRow"
      num_consumers        = 1
      max_block_size       = 10000
      skip_broken_messages = 100
      poll_timeout_ms      = 10000
      poll_max_batch_size  = 10000
      flush_interval_ms    = 7500
    }
  }

  materialized_view "flag_evaluations_json_mv" {
    to_table = "posthog.writable_flag_evaluations_json"
    query    = file("sql/flag_evaluations_json_mv.sql")

    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "LowCardinality(String)"
    }
    column "properties" {
      type = "JSON(`$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$config_defaults` LowCardinality(String), `$current_url` String, `$device_type` LowCardinality(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$host` String, `$lib` LowCardinality(String), `$lib_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String), `$pathname` String, `$session_id` String, `$timezone` LowCardinality(String), `$window_id` String)"
    }
    column "temporary_properties" {
      type = "JSON(max_dynamic_paths=32)"
    }
    column "properties_null_keys" {
      type = "Array(String)"
    }
    column "temporary_properties_null_keys" {
      type = "Array(String)"
    }
    column "inserted_at" {
      type = "DateTime64(3)"
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
      type = "DateTime64(6, 'UTC')"
    }
    column "person_id" {
      type = "UUID"
    }
    column "person_properties" {
      type = "JSON(max_dynamic_paths=256, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$device_type` LowCardinality(String), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$initial_browser` LowCardinality(String), `$initial_browser_language` LowCardinality(String), `$initial_browser_version` LowCardinality(String), `$initial_device_type` LowCardinality(String), `$initial_geoip_city_name` LowCardinality(String), `$initial_geoip_continent_code` LowCardinality(String), `$initial_geoip_continent_name` LowCardinality(String), `$initial_geoip_country_code` LowCardinality(String), `$initial_geoip_country_name` LowCardinality(String), `$initial_geoip_subdivision_1_name` LowCardinality(String), `$initial_geoip_time_zone` LowCardinality(String), `$initial_os` LowCardinality(String), `$initial_os_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String))"
    }
    column "person_properties_null_keys" {
      type = "Array(String)"
    }
    column "person_created_at" {
      type = "DateTime64(3)"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "captured_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "_timestamp" {
      type = "Nullable(DateTime)"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_partition" {
      type = "UInt64"
    }
    column "total_event_size" {
      type = "UInt32"
    }
  }
}

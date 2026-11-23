SELECT
  *,
  accurateCast(byteSize(*) + byteSize(toUInt32(0)), 'UInt32') AS total_event_size
FROM
  (
    SELECT
      uuid,
      event,
      ifNull(
        accurateCastOrNull(
          cleaned.properties,
          'JSON(max_dynamic_paths = 1024, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$config_defaults` LowCardinality(String), `$current_url` String, `$device_type` LowCardinality(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$host` String, `$lib` LowCardinality(String), `$lib_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String), `$pathname` String, `$session_id` String, `$timezone` LowCardinality(String), `$window_id` String)'
        ),
        CAST(concat('{"$unparseable_properties":', toJSONString(source.properties), '}'), 'JSON(max_dynamic_paths = 1024, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$config_defaults` LowCardinality(String), `$current_url` String, `$device_type` LowCardinality(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$host` String, `$lib` LowCardinality(String), `$lib_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String), `$pathname` String, `$session_id` String, `$timezone` LowCardinality(String), `$window_id` String)')
      ) AS properties,
      ifNull(
        accurateCastOrNull(cleaned.temporary_properties, 'JSON(max_dynamic_paths = 32)'),
        CAST('{}', 'JSON(max_dynamic_paths = 32)')
      ) AS temporary_properties,
      cleaned.properties_null_keys AS properties_null_keys,
      cleaned.temporary_properties_null_keys AS temporary_properties_null_keys,
      now64() AS inserted_at,
      timestamp,
      team_id,
      distinct_id,
      created_at,
      person_id,
      ifNull(
        accurateCastOrNull(
          cleaned.person_properties,
          'JSON(max_dynamic_paths = 256, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$device_type` LowCardinality(String), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$initial_browser` LowCardinality(String), `$initial_browser_language` LowCardinality(String), `$initial_browser_version` LowCardinality(String), `$initial_device_type` LowCardinality(String), `$initial_geoip_city_name` LowCardinality(String), `$initial_geoip_continent_code` LowCardinality(String), `$initial_geoip_continent_name` LowCardinality(String), `$initial_geoip_country_code` LowCardinality(String), `$initial_geoip_country_name` LowCardinality(String), `$initial_geoip_subdivision_1_name` LowCardinality(String), `$initial_geoip_time_zone` LowCardinality(String), `$initial_os` LowCardinality(String), `$initial_os_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String))'
        ),
        CAST(concat('{"$unparseable_properties":', toJSONString(source.person_properties), '}'), 'JSON(max_dynamic_paths = 256, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$device_type` LowCardinality(String), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$initial_browser` LowCardinality(String), `$initial_browser_language` LowCardinality(String), `$initial_browser_version` LowCardinality(String), `$initial_device_type` LowCardinality(String), `$initial_geoip_city_name` LowCardinality(String), `$initial_geoip_continent_code` LowCardinality(String), `$initial_geoip_continent_name` LowCardinality(String), `$initial_geoip_country_code` LowCardinality(String), `$initial_geoip_country_name` LowCardinality(String), `$initial_geoip_subdivision_1_name` LowCardinality(String), `$initial_geoip_time_zone` LowCardinality(String), `$initial_os` LowCardinality(String), `$initial_os_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String))')
      ) AS person_properties,
      cleaned.person_properties_null_keys AS person_properties_null_keys,
      person_created_at,
      person_mode,
      created_at AS captured_at,
      _timestamp,
      _offset,
      _partition
    FROM
      (
        SELECT
          *,
          _timestamp,
          _offset,
          _partition,
          JSONCleanPostHogEvent(properties, if(empty(person_properties), '{}', person_properties)) AS cleaned
        FROM posthog.kafka_flag_evaluations_json
      ) AS source
  )
SETTINGS
  input_format_try_infer_dates = 0,
  input_format_try_infer_datetimes = 0,
  json_type_escape_dots_in_keys = 1,
  type_json_skip_duplicated_paths = 1

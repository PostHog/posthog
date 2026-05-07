CREATE MATERIALIZED VIEW IF NOT EXISTS raw_sessions_v3_recordings_mv
TO default.writable_raw_sessions_v3
AS

WITH
    min_first_timestamp as timestamp,
    CAST(fromUnixTimestamp64Milli(9223372036854775), 'DateTime64(6)') as max_ts_64, -- max positive Int64 / 1000
    CAST(fromUnixTimestamp64Milli(-9223372036854775), 'DateTime64(6)') as min_ts_64, -- max negative Int64 / 1000
    CAST(NULL, 'Nullable(String)') as null_s,
    CAST(NULL, 'Nullable(Int64)') as null_i64,
    CAST(NULL, 'Nullable(UUID)') as null_uuid
SELECT
    team_id,
    toUInt128(accurateCast(session_id, 'UUID')) AS session_id_v7,
    fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80))) AS session_timestamp,
    initializeAggregation('argMaxState', source_table.distinct_id, min_ts_64) as distinct_id,
    initializeAggregation('groupUniqArrayState', source_table.distinct_id) as distinct_ids,

    timestamp AS min_timestamp,
    timestamp AS max_timestamp,
    fromUnixTimestamp(0) AS max_inserted_at,

    -- urls - only update if the event is a pageview or screen
    CAST([], 'Array(String)') AS urls,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_url,
    initializeAggregation('argMaxState', null_s, min_ts_64) as end_url,
    initializeAggregation('argMaxState', null_s, min_ts_64) as last_external_click_url,

    -- device
    initializeAggregation('argMinState', null_s, max_ts_64) as browser,
    initializeAggregation('argMinState', null_s, max_ts_64) as browser_version,
    initializeAggregation('argMinState', null_s, max_ts_64) as os,
    initializeAggregation('argMinState', null_s, max_ts_64) as os_version,
    initializeAggregation('argMinState', null_s, max_ts_64) as device_type,
    initializeAggregation('argMinState', null_i64, max_ts_64) as viewport_width,
    initializeAggregation('argMinState', null_i64, max_ts_64) as viewport_height,

    -- geo ip
    initializeAggregation('argMinState', null_s, max_ts_64) as geoip_country_code,
    initializeAggregation('argMinState', null_s, max_ts_64) as geoip_subdivision_1_code,
    initializeAggregation('argMinState', null_s, max_ts_64) as geoip_subdivision_1_name,
    initializeAggregation('argMinState', null_s, max_ts_64) as geoip_subdivision_city_name,
    initializeAggregation('argMinState', null_s, max_ts_64) as geoip_time_zone,

    -- attribution
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_referring_domain,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_utm_source,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_utm_campaign,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_utm_medium,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_utm_term,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_utm_content,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_gclid,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_gad_source,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_fbclid,

    -- has gclid/fbclid for reading fewer bytes when calculating channel type
    initializeAggregation('argMinState', false, max_ts_64) as entry_has_gclid,
    initializeAggregation('argMinState', false, max_ts_64) as entry_has_fbclid,

    -- other ad ids
    initializeAggregation('argMinState', CAST(map(), 'Map(String, String)'), max_ts_64) as entry_ad_ids_map,
    initializeAggregation('argMinState', CAST([], 'Array(String)'), max_ts_64) as entry_ad_ids_set,

    -- channel type
    initializeAggregation('argMinState', tuple(null_s, null_s, null_s, null_s, false, false, null_s), max_ts_64) as entry_channel_type_properties,

    -- counts
    initializeAggregation('uniqExactState', null_uuid) as pageview_uniq,
    initializeAggregation('uniqExactState', null_uuid) as autocapture_uniq,
    initializeAggregation('uniqExactState', null_uuid) as screen_uniq,

    -- perf
    initializeAggregation('uniqUpToState(1)', null_uuid) as page_screen_uniq_up_to,
    false as has_autocapture,

    -- flags
    initializeAggregation('groupUniqArrayMapState', CAST(map(), 'Map(String, String)')) as flag_values,
    CAST([], 'Array(String)') as flag_keys,

    -- event names
    CAST([], 'Array(String)') as event_names,

    -- hosts
    CAST([], 'Array(String)') as hosts,

    -- emails
    CAST([], 'Array(String)') as emails,

    -- replay
    true as has_replay_events
FROM default.sharded_session_replay_events AS source_table
WHERE bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(session_id, 'UUID')), 76), 0xF) == 7 -- has a session id and is valid uuidv7
AND TRUE

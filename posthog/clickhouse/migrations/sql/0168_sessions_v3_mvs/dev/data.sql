CREATE MATERIALIZED VIEW IF NOT EXISTS raw_sessions_v3_mv
TO default.writable_raw_sessions_v3
AS

WITH
    
        JSONExtract(properties, 'Tuple(
            `$current_url` Nullable(String),
            `$external_click_url` Nullable(String),
            `$browser` Nullable(String),
            `$browser_version` Nullable(String),
            `$os` Nullable(String),
            `$os_version` Nullable(String),
            `$device_type` Nullable(String),
            `$viewport_width` Nullable(Int64),
            `$viewport_height` Nullable(Int64),
            `$geoip_country_code` Nullable(String),
            `$geoip_subdivision_1_code` Nullable(String),
            `$geoip_subdivision_1_name` Nullable(String),
            `$geoip_subdivision_city_name` Nullable(String),
            `$geoip_time_zone` Nullable(String),
            `$referring_domain` Nullable(String),
            `utm_source` Nullable(String),
            `utm_campaign` Nullable(String),
            `utm_medium` Nullable(String),
            `utm_term` Nullable(String),
            `utm_content` Nullable(String),
            `gclid` Nullable(String),
            `gad_source` Nullable(String),
            `fbclid` Nullable(String),
            `$host` Nullable(String),
            `gclsrc` Nullable(String),
            `dclid` Nullable(String),
            `gbraid` Nullable(String),
            `wbraid` Nullable(String),
            `msclkid` Nullable(String),
            `twclid` Nullable(String),
            `li_fat_id` Nullable(String),
            `mc_cid` Nullable(String),
            `igshid` Nullable(String),
            `ttclid` Nullable(String),
            `epik` Nullable(String),
            `qclid` Nullable(String),
            `sccid` Nullable(String),
            `_kx` Nullable(String),
            `irclid` Nullable(String)
        )') as p,
        JSONExtractString(person_properties, 'email') as _person_email,
        tupleElement(p, '$current_url') as _current_url,
        tupleElement(p, '$external_click_url') as _external_click_url,
        tupleElement(p, '$browser') as _browser,
        tupleElement(p, '$browser_version') as _browser_version,
        tupleElement(p, '$os') as _os,
        tupleElement(p, '$os_version') as _os_version,
        tupleElement(p, '$device_type') as _device_type,
        tupleElement(p, '$viewport_width') as _viewport_width,
        tupleElement(p, '$viewport_height') as _viewport_height,
        tupleElement(p, '$geoip_country_code') as _geoip_country_code,
        tupleElement(p, '$geoip_subdivision_1_code') as _geoip_subdivision_1_code,
        tupleElement(p, '$geoip_subdivision_1_name') as _geoip_subdivision_1_name,
        tupleElement(p, '$geoip_subdivision_city_name') as _geoip_subdivision_city_name,
        tupleElement(p, '$geoip_time_zone') as _geoip_time_zone,
        tupleElement(p, '$referring_domain') as _referring_domain,
        tupleElement(p, 'utm_source') as _utm_source,
        tupleElement(p, 'utm_campaign') as _utm_campaign,
        tupleElement(p, 'utm_medium') as _utm_medium,
        tupleElement(p, 'utm_term') as _utm_term,
        tupleElement(p, 'utm_content') as _utm_content,
        tupleElement(p, 'gclid') as _gclid,
        tupleElement(p, 'gad_source') as _gad_source,
        tupleElement(p, 'fbclid') as _fbclid,
        tupleElement(p, 'gclsrc') as gclsrc,
        tupleElement(p, 'dclid') as dclid,
        tupleElement(p, 'gbraid') as gbraid,
        tupleElement(p, 'wbraid') as wbraid,
        tupleElement(p, 'msclkid') as msclkid,
        tupleElement(p, 'twclid') as twclid,
        tupleElement(p, 'li_fat_id') as li_fat_id,
        tupleElement(p, 'mc_cid') as mc_cid,
        tupleElement(p, 'igshid') as igshid,
        tupleElement(p, 'ttclid') as ttclid,
        tupleElement(p, 'epik') as epik,
        tupleElement(p, 'qclid') as qclid,
        tupleElement(p, 'sccid') as sccid,
        tupleElement(p, '_kx') as _kx,
        tupleElement(p, 'irclid') as irclid,
        CAST(mapFilter((k, v) -> v IS NOT NULL, map(
            'gclsrc', gclsrc,
            'dclid', dclid,
            'gbraid', gbraid,
            'wbraid', wbraid,
            'msclkid', msclkid,
            'twclid', twclid,
            'li_fat_id', li_fat_id,
            'mc_cid', mc_cid,
            'igshid', igshid,
            'ttclid', ttclid,
            'epik', epik,
            'qclid', qclid,
            'sccid', sccid,
            '_kx', _kx,
            'irclid', irclid
        )) AS Map(String, String)) as ad_ids_map,
        CAST(arrayFilter(x -> x IS NOT NULL, [
            if(gclsrc IS NOT NULL, 'gclsrc', NULL),
            if(dclid IS NOT NULL, 'dclid', NULL),
            if(gbraid IS NOT NULL, 'gbraid', NULL),
            if(wbraid IS NOT NULL, 'wbraid', NULL),
            if(msclkid IS NOT NULL, 'msclkid', NULL),
            if(twclid IS NOT NULL, 'twclid', NULL),
            if(li_fat_id IS NOT NULL, 'li_fat_id', NULL),
            if(mc_cid IS NOT NULL, 'mc_cid', NULL),
            if(igshid IS NOT NULL, 'igshid', NULL),
            if(ttclid IS NOT NULL, 'ttclid', NULL),
            if(epik IS NOT NULL, 'epik', NULL),
            if(qclid IS NOT NULL, 'qclid', NULL),
            if(sccid IS NOT NULL, 'sccid', NULL),
            if(_kx IS NOT NULL, '_kx', NULL),
            if(irclid IS NOT NULL, 'irclid', NULL)
        ]) AS Array(String)) as ad_ids_set,
        tupleElement(p, '$host') as _host,
    -- attribution properties from non-pageview/screen events should be deprioritized, so make the timestamp +/- 1 year so they sort last
    if (event = '$pageview' OR event = '$screen', timestamp, timestamp + toIntervalYear(1)) as pageview_prio_timestamp_min,
    if (event = '$pageview' OR event = '$screen', timestamp, timestamp - toIntervalYear(1)) as pageview_prio_timestamp_max
SELECT
    team_id,
    `$session_id_uuid` AS session_id_v7,
    

    initializeAggregation('argMaxState', source_table.distinct_id, timestamp) as distinct_id,
    initializeAggregation('groupUniqArrayState', source_table.distinct_id) as distinct_ids,

    timestamp AS min_timestamp,
    timestamp AS max_timestamp,
    inserted_at AS max_inserted_at,

    -- urls - only update if the event is a pageview or screen
    if(_current_url IS NOT NULL AND (event = '$pageview' OR event = '$screen'), [_current_url], []) AS urls,
    initializeAggregation('argMinState', _current_url, pageview_prio_timestamp_min) as entry_url,
    initializeAggregation('argMaxState', _current_url, pageview_prio_timestamp_max) as end_url,
    initializeAggregation('argMaxState', _external_click_url, timestamp) as last_external_click_url,

    -- device
    initializeAggregation('argMinState', _browser, timestamp) as browser,
    initializeAggregation('argMinState', _browser_version, timestamp) as browser_version,
    initializeAggregation('argMinState', _os, timestamp) as os,
    initializeAggregation('argMinState', _os_version, timestamp) as os_version,
    initializeAggregation('argMinState', _device_type, timestamp) as device_type,
    initializeAggregation('argMinState', _viewport_width, timestamp) as viewport_width,
    initializeAggregation('argMinState', _viewport_height, timestamp) as viewport_height,

    -- geo ip
    initializeAggregation('argMinState', _geoip_country_code, timestamp) as geoip_country_code,
    initializeAggregation('argMinState', _geoip_subdivision_1_code, timestamp) as geoip_subdivision_1_code,
    initializeAggregation('argMinState', _geoip_subdivision_1_name, timestamp) as geoip_subdivision_1_name,
    initializeAggregation('argMinState', _geoip_subdivision_city_name, timestamp) as geoip_subdivision_city_name,
    initializeAggregation('argMinState', _geoip_time_zone, timestamp) as geoip_time_zone,

    -- attribution
    initializeAggregation('argMinState', _referring_domain, pageview_prio_timestamp_min) as entry_referring_domain,
    initializeAggregation('argMinState', _utm_source, pageview_prio_timestamp_min) as entry_utm_source,
    initializeAggregation('argMinState', _utm_campaign, pageview_prio_timestamp_min) as entry_utm_campaign,
    initializeAggregation('argMinState', _utm_medium, pageview_prio_timestamp_min) as entry_utm_medium,
    initializeAggregation('argMinState', _utm_term, pageview_prio_timestamp_min) as entry_utm_term,
    initializeAggregation('argMinState', _utm_content, pageview_prio_timestamp_min) as entry_utm_content,
    initializeAggregation('argMinState', _gclid, pageview_prio_timestamp_min) as entry_gclid,
    initializeAggregation('argMinState', _gad_source, pageview_prio_timestamp_min) as entry_gad_source,
    initializeAggregation('argMinState', _fbclid, pageview_prio_timestamp_min) as entry_fbclid,

    -- has gclid/fbclid for reading fewer bytes when calculating channel type
    initializeAggregation('argMinState', _gclid IS NOT NULL, pageview_prio_timestamp_min) as entry_has_gclid,
    initializeAggregation('argMinState', _fbclid IS NOT NULL, pageview_prio_timestamp_min) as entry_has_fbclid,

    -- other ad ids
    initializeAggregation('argMinState', ad_ids_map, pageview_prio_timestamp_min) as entry_ad_ids_map,
    initializeAggregation('argMinState', ad_ids_set, pageview_prio_timestamp_min) as entry_ad_ids_set,

    -- channel type
    initializeAggregation('argMinState', tuple(_utm_source, _utm_medium, _utm_campaign, _referring_domain, _gclid IS NOT NULL, _fbclid IS NOT NULL, _gad_source), pageview_prio_timestamp_min) as entry_channel_type_properties,


    -- counts
    initializeAggregation('uniqExactState', if(event='$pageview', uuid, NULL)) as pageview_uniq,
    initializeAggregation('uniqExactState', if(event='$autocapture', uuid, NULL)) as autocapture_uniq,
    initializeAggregation('uniqExactState', if(event='$screen', uuid, NULL)) as screen_uniq,

    -- perf
    initializeAggregation('uniqUpToState(1)', if(event='$pageview' OR event='$screen', uuid, NULL)) as page_screen_uniq_up_to,
    event = '$autocapture' as has_autocapture,

    -- flags
    initializeAggregation('groupUniqArrayMapState', properties_group_feature_flags) as flag_values,
    mapKeys(properties_group_feature_flags) as flag_keys,

    -- event names
    [event] as event_names,

    -- hosts
    if(_host IS NOT NULL AND _host != '', [_host], []) AS hosts,

    -- emails
    if(_person_email IS NOT NULL AND _person_email != '', [_person_email], []) AS emails,

    false as has_replay_events
FROM default.sharded_events AS source_table
WHERE bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(`$session_id`, 'UUID')), 76), 0xF) == 7 -- has a session id and is valid uuidv7
AND TRUE

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

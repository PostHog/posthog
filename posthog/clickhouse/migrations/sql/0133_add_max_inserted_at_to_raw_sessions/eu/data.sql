ALTER TABLE sharded_raw_sessions 
ADD COLUMN IF NOT EXISTS
max_inserted_at SimpleAggregateFunction(max, DateTime64(6, 'UTC'))
AFTER max_timestamp

ALTER TABLE writable_raw_sessions 
ADD COLUMN IF NOT EXISTS
max_inserted_at SimpleAggregateFunction(max, DateTime64(6, 'UTC'))
AFTER max_timestamp

ALTER TABLE raw_sessions_mv 
MODIFY QUERY

SELECT
    team_id,
    toUInt128(toUUID(`$session_id`)) as session_id_v7,

    argMaxState(distinct_id, timestamp) as distinct_id,

    min(timestamp) AS min_timestamp,
    max(timestamp) AS max_timestamp,
    max(coalesce(inserted_at, now64())) AS max_inserted_at, -- use coalesce to ensure we have a value even if the event is created with inserted_at=NULL

    -- urls
    groupUniqArray(nullIf(JSONExtractString(properties, '$current_url'), '')) AS urls,
    argMinState(JSONExtractString(properties, '$current_url'), timestamp) as entry_url,
    argMaxState(JSONExtractString(properties, '$current_url'), timestamp) as end_url,
    argMaxState(JSONExtractString(properties, '$external_click_url'), timestamp) as last_external_click_url,

    -- device
    argMinState(JSONExtractString(properties, '$browser'), timestamp) as initial_browser,
    argMinState(JSONExtractString(properties, '$browser_version'), timestamp) as initial_browser_version,
    argMinState(JSONExtractString(properties, '$os'), timestamp) as initial_os,
    argMinState(JSONExtractString(properties, '$os_version'), timestamp) as initial_os_version,
    argMinState(JSONExtractString(properties, '$device_type'), timestamp) as initial_device_type,
    argMinState(JSONExtractInt(properties, '$viewport_width'), timestamp) as initial_viewport_width,
    argMinState(JSONExtractInt(properties, '$viewport_height'), timestamp) as initial_viewport_height,

    -- geoip
    argMinState(JSONExtractString(properties, '$geoip_country_code'), timestamp) as initial_geoip_country_code,
    argMinState(JSONExtractString(properties, '$geoip_subdivision_1_code'), timestamp) as initial_geoip_subdivision_1_code,
    argMinState(JSONExtractString(properties, '$geoip_subdivision_1_name'), timestamp) as initial_geoip_subdivision_1_name,
    argMinState(JSONExtractString(properties, '$geoip_subdivision_city_name'), timestamp) as initial_geoip_subdivision_city_name,
    argMinState(JSONExtractString(properties, '$geoip_time_zone'), timestamp) as initial_geoip_time_zone,

    -- attribution
    argMinState(JSONExtractString(properties, '$referring_domain'), timestamp) as initial_referring_domain,
    argMinState(JSONExtractString(properties, 'utm_source'), timestamp) as initial_utm_source,
    argMinState(JSONExtractString(properties, 'utm_campaign'), timestamp) as initial_utm_campaign,
    argMinState(JSONExtractString(properties, 'utm_medium'), timestamp) as initial_utm_medium,
    argMinState(JSONExtractString(properties, 'utm_term'), timestamp) as initial_utm_term,
    argMinState(JSONExtractString(properties, 'utm_content'), timestamp) as initial_utm_content,
    argMinState(JSONExtractString(properties, 'gclid'), timestamp) as initial_gclid,
    argMinState(JSONExtractString(properties, 'gad_source'), timestamp) as initial_gad_source,
    argMinState(JSONExtractString(properties, 'gclsrc'), timestamp) as initial_gclsrc,
    argMinState(JSONExtractString(properties, 'dclid'), timestamp) as initial_dclid,
    argMinState(JSONExtractString(properties, 'gbraid'), timestamp) as initial_gbraid,
    argMinState(JSONExtractString(properties, 'wbraid'), timestamp) as initial_wbraid,
    argMinState(JSONExtractString(properties, 'fbclid'), timestamp) as initial_fbclid,
    argMinState(JSONExtractString(properties, 'msclkid'), timestamp) as initial_msclkid,
    argMinState(JSONExtractString(properties, 'twclid'), timestamp) as initial_twclid,
    argMinState(JSONExtractString(properties, 'li_fat_id'), timestamp) as initial_li_fat_id,
    argMinState(JSONExtractString(properties, 'mc_cid'), timestamp) as initial_mc_cid,
    argMinState(JSONExtractString(properties, 'igshid'), timestamp) as initial_igshid,
    argMinState(JSONExtractString(properties, 'ttclid'), timestamp) as initial_ttclid,
    argMinState(JSONExtractString(properties, 'epik'), timestamp) as initial_epik,
    argMinState(JSONExtractString(properties, 'qclid'), timestamp) as initial_qclid,
    argMinState(JSONExtractString(properties, 'sccid'), timestamp) as initial_sccid,
    argMinState(JSONExtractString(properties, '_kx'), timestamp) as initial__kx,
    argMinState(JSONExtractString(properties, 'irclid'), timestamp) as initial_irclid,

    -- count
    sumIf(1, event='$pageview') as pageview_count,
    uniqState(CAST(if(event='$pageview', uuid, NULL) AS Nullable(UUID))) as pageview_uniq,
    sumIf(1, event='$autocapture') as autocapture_count,
    uniqState(CAST(if(event='$autocapture', uuid, NULL) AS Nullable(UUID))) as autocapture_uniq,
    sumIf(1, event='$screen') as screen_count,
    uniqState(CAST(if(event='$screen', uuid, NULL) AS Nullable(UUID))) as screen_uniq,

    -- replay
    false as maybe_has_session_replay,

    -- perf
    uniqUpToState(1)(CAST(if(event='$pageview' OR event='$screen' OR event='$autocapture', uuid, NULL) AS Nullable(UUID))) as page_screen_autocapture_uniq_up_to,

    -- web vitals
    argMinState(accurateCastOrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, '$web_vitals_LCP_value'), ''), 'null'), '^"|"$', ''), 'Float64'), timestamp) as vitals_lcp
FROM default.sharded_events
WHERE bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(`$session_id`, 'UUID')), 76), 0xF) == 7 -- has a session id and is valid uuidv7)
GROUP BY
    team_id,
    toStartOfHour(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000))),
    cityHash64(session_id_v7),
    session_id_v7

CREATE OR REPLACE VIEW raw_sessions_v  AS
SELECT
    session_id_v7,
    fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000)) as session_timestamp,
    team_id,
    argMaxMerge(distinct_id) as distinct_id,
    min(min_timestamp) as min_timestamp,
    max(max_timestamp) as max_timestamp,
    max(max_inserted_at) as max_inserted_at,

    -- urls
    arrayDistinct(arrayFlatten(groupArray(urls)) )AS urls,
    argMinMerge(entry_url) as entry_url,
    argMaxMerge(end_url) as end_url,
    argMaxMerge(last_external_click_url) as last_external_click_url,

    -- device
    argMinMerge(initial_browser) as initial_browser,
    argMinMerge(initial_browser_version) as initial_browser_version,
    argMinMerge(initial_os) as initial_os,
    argMinMerge(initial_os_version) as initial_os_version,
    argMinMerge(initial_device_type) as initial_device_type,
    argMinMerge(initial_viewport_width) as initial_viewport_width,
    argMinMerge(initial_viewport_height) as initial_viewport_height,

    -- geoip
    argMinMerge(initial_geoip_country_code) as initial_geoip_country_code,
    argMinMerge(initial_geoip_subdivision_1_code) as initial_geoip_subdivision_1_code,
    argMinMerge(initial_geoip_subdivision_1_name) as initial_geoip_subdivision_1_name,
    argMinMerge(initial_geoip_subdivision_city_name) as initial_geoip_subdivision_city_name,
    argMinMerge(initial_geoip_time_zone) as initial_geoip_time_zone,

    -- attribution
    argMinMerge(initial_utm_source) as initial_utm_source,
    argMinMerge(initial_utm_campaign) as initial_utm_campaign,
    argMinMerge(initial_utm_medium) as initial_utm_medium,
    argMinMerge(initial_utm_term) as initial_utm_term,
    argMinMerge(initial_utm_content) as initial_utm_content,
    argMinMerge(initial_referring_domain) as initial_referring_domain,
    argMinMerge(initial_gclid) as initial_gclid,
    argMinMerge(initial_gad_source) as initial_gad_source,
    argMinMerge(initial_gclsrc) as initial_gclsrc,
    argMinMerge(initial_dclid) as initial_dclid,
    argMinMerge(initial_gbraid) as initial_gbraid,
    argMinMerge(initial_wbraid) as initial_wbraid,
    argMinMerge(initial_fbclid) as initial_fbclid,
    argMinMerge(initial_msclkid) as initial_msclkid,
    argMinMerge(initial_twclid) as initial_twclid,
    argMinMerge(initial_li_fat_id) as initial_li_fat_id,
    argMinMerge(initial_mc_cid) as initial_mc_cid,
    argMinMerge(initial_igshid) as initial_igshid,
    argMinMerge(initial_ttclid) as initial_ttclid,
    argMinMerge(initial__kx) as initial__kx,
    argMinMerge(initial_irclid) as initial_irclid,

    sum(pageview_count) as pageview_count,
    uniqMerge(pageview_uniq) as pageview_uniq,
    sum(autocapture_count) as autocapture_count,
    uniqMerge(autocapture_uniq) as autocapture_uniq,
    sum(screen_count) as screen_count,
    uniqMerge(screen_uniq) as screen_uniq,

    max(maybe_has_session_replay) as maybe_has_session_replay,

    uniqUpToMerge(1)(page_screen_autocapture_uniq_up_to) as page_screen_autocapture_uniq_up_to,

    argMinMerge(vitals_lcp) as vitals_lcp
FROM raw_sessions
GROUP BY session_id_v7, team_id

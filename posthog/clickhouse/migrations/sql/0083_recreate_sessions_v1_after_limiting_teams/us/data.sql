DROP TABLE IF EXISTS sessions_mv ON CLUSTER 'posthog'

CREATE MATERIALIZED VIEW IF NOT EXISTS sessions_mv ON CLUSTER 'posthog'
TO default.writable_sessions
AS

SELECT

`$session_id` as session_id,
team_id,

-- it doesn't matter which distinct_id gets picked (it'll be somewhat random) as they can all join to the right person
any(distinct_id) as distinct_id,

min(timestamp) AS min_timestamp,
max(timestamp) AS max_timestamp,

groupUniqArray(replaceRegexpAll(JSONExtractRaw(properties, '$current_url'), '^"|"$', '')) AS urls,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, '$current_url'), '^"|"$', ''), timestamp) as entry_url,
argMaxState(replaceRegexpAll(JSONExtractRaw(properties, '$current_url'), '^"|"$', ''), timestamp) as exit_url,

argMinState(replaceRegexpAll(JSONExtractRaw(properties, '$referring_domain'), '^"|"$', ''), timestamp) as initial_referring_domain,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_source'), '^"|"$', ''), timestamp) as initial_utm_source,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_campaign'), '^"|"$', ''), timestamp) as initial_utm_campaign,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_medium'), '^"|"$', ''), timestamp) as initial_utm_medium,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_term'), '^"|"$', ''), timestamp) as initial_utm_term,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_content'), '^"|"$', ''), timestamp) as initial_utm_content,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gclid'), '^"|"$', ''), timestamp) as initial_gclid,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gad_source'), '^"|"$', ''), timestamp) as initial_gad_source,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gclsrc'), '^"|"$', ''), timestamp) as initial_gclsrc,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'dclid'), '^"|"$', ''), timestamp) as initial_dclid,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gbraid'), '^"|"$', ''), timestamp) as initial_gbraid,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'wbraid'), '^"|"$', ''), timestamp) as initial_wbraid,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'fbclid'), '^"|"$', ''), timestamp) as initial_fbclid,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'msclkid'), '^"|"$', ''), timestamp) as initial_msclkid,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'twclid'), '^"|"$', ''), timestamp) as initial_twclid,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'li_fat_id'), '^"|"$', ''), timestamp) as initial_li_fat_id,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'mc_cid'), '^"|"$', ''), timestamp) as initial_mc_cid,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'igshid'), '^"|"$', ''), timestamp) as initial_igshid,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'ttclid'), '^"|"$', ''), timestamp) as initial_ttclid,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'epik'), '^"|"$', ''), timestamp) as initial_epik,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'qclid'), '^"|"$', ''), timestamp) as initial_qclid,
argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'sccid'), '^"|"$', ''), timestamp) as initial_sccid,

sumMap(CAST(([event], [1]), 'Map(String, UInt64)')) as event_count_map,
sumIf(1, event='$pageview') as pageview_count,
sumIf(1, event='$autocapture') as autocapture_count

FROM default.sharded_events
WHERE `$session_id` IS NOT NULL AND `$session_id` != '' AND team_id IN (1, 2, 13610, 19279, 21173, 29929, 32050, 9910, 11775, 21129, 31490)
GROUP BY `$session_id`, team_id

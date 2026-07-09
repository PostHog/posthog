SELECT
  `$session_id` AS session_id,
  team_id,
  any(distinct_id) AS distinct_id,
  min(timestamp) AS min_timestamp,
  max(timestamp) AS max_timestamp,
  groupUniqArray(replaceRegexpAll(JSONExtractRaw(properties, '$current_url'), '^"|"$', '')) AS urls,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, '$current_url'), '^"|"$', ''), timestamp) AS entry_url,
  argMaxState(replaceRegexpAll(JSONExtractRaw(properties, '$current_url'), '^"|"$', ''), timestamp) AS exit_url,
  argMinState(
    replaceRegexpAll(JSONExtractRaw(properties, '$referring_domain'), '^"|"$', ''),
    timestamp
  ) AS initial_referring_domain,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_source'), '^"|"$', ''), timestamp) AS initial_utm_source,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_campaign'), '^"|"$', ''), timestamp) AS initial_utm_campaign,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_medium'), '^"|"$', ''), timestamp) AS initial_utm_medium,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_term'), '^"|"$', ''), timestamp) AS initial_utm_term,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_content'), '^"|"$', ''), timestamp) AS initial_utm_content,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gclid'), '^"|"$', ''), timestamp) AS initial_gclid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gad_source'), '^"|"$', ''), timestamp) AS initial_gad_source,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gclsrc'), '^"|"$', ''), timestamp) AS initial_gclsrc,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'dclid'), '^"|"$', ''), timestamp) AS initial_dclid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gbraid'), '^"|"$', ''), timestamp) AS initial_gbraid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'wbraid'), '^"|"$', ''), timestamp) AS initial_wbraid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'fbclid'), '^"|"$', ''), timestamp) AS initial_fbclid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'msclkid'), '^"|"$', ''), timestamp) AS initial_msclkid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'twclid'), '^"|"$', ''), timestamp) AS initial_twclid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'li_fat_id'), '^"|"$', ''), timestamp) AS initial_li_fat_id,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'mc_cid'), '^"|"$', ''), timestamp) AS initial_mc_cid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'igshid'), '^"|"$', ''), timestamp) AS initial_igshid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'ttclid'), '^"|"$', ''), timestamp) AS initial_ttclid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'epik'), '^"|"$', ''), timestamp) AS initial_epik,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'qclid'), '^"|"$', ''), timestamp) AS initial_qclid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'sccid'), '^"|"$', ''), timestamp) AS initial_sccid,
  sumMap(CAST(([event], [1]), 'Map(String, UInt64)')) AS event_count_map,
  sumIf(1, event = '$pageview') AS pageview_count,
  sumIf(1, event = '$autocapture') AS autocapture_count
FROM posthog.sharded_events
WHERE
  (`$session_id` IS NOT NULL)
AND
  (`$session_id` != '')
AND
  (team_id IN (1, 2, 13610, 19279, 21173, 29929, 32050, 9910, 11775, 21129, 31490))
GROUP BY
  `$session_id`, team_id

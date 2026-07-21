SELECT
  team_id,
  toUInt128(toUUID(`$session_id`)) AS session_id_v7,
  argMaxState(distinct_id, timestamp) AS distinct_id,
  min(timestamp) AS min_timestamp,
  max(timestamp) AS max_timestamp,
  max(coalesce(inserted_at, now64())) AS max_inserted_at,
  groupUniqArray(nullIf(JSONExtractString(properties, '$current_url'), '')) AS urls,
  argMinState(JSONExtractString(properties, '$current_url'), timestamp) AS entry_url,
  argMaxState(JSONExtractString(properties, '$current_url'), timestamp) AS end_url,
  argMaxState(JSONExtractString(properties, '$external_click_url'), timestamp) AS last_external_click_url,
  argMinState(JSONExtractString(properties, '$browser'), timestamp) AS initial_browser,
  argMinState(JSONExtractString(properties, '$browser_version'), timestamp) AS initial_browser_version,
  argMinState(JSONExtractString(properties, '$os'), timestamp) AS initial_os,
  argMinState(JSONExtractString(properties, '$os_version'), timestamp) AS initial_os_version,
  argMinState(JSONExtractString(properties, '$device_type'), timestamp) AS initial_device_type,
  argMinState(JSONExtractInt(properties, '$viewport_width'), timestamp) AS initial_viewport_width,
  argMinState(JSONExtractInt(properties, '$viewport_height'), timestamp) AS initial_viewport_height,
  argMinState(JSONExtractString(properties, '$geoip_country_code'), timestamp) AS initial_geoip_country_code,
  argMinState(JSONExtractString(properties, '$geoip_subdivision_1_code'), timestamp) AS initial_geoip_subdivision_1_code,
  argMinState(JSONExtractString(properties, '$geoip_subdivision_1_name'), timestamp) AS initial_geoip_subdivision_1_name,
  argMinState(JSONExtractString(properties, '$geoip_subdivision_city_name'), timestamp) AS initial_geoip_subdivision_city_name,
  argMinState(JSONExtractString(properties, '$geoip_time_zone'), timestamp) AS initial_geoip_time_zone,
  argMinState(JSONExtractString(properties, '$referring_domain'), timestamp) AS initial_referring_domain,
  argMinState(JSONExtractString(properties, 'utm_source'), timestamp) AS initial_utm_source,
  argMinState(JSONExtractString(properties, 'utm_campaign'), timestamp) AS initial_utm_campaign,
  argMinState(JSONExtractString(properties, 'utm_medium'), timestamp) AS initial_utm_medium,
  argMinState(JSONExtractString(properties, 'utm_term'), timestamp) AS initial_utm_term,
  argMinState(JSONExtractString(properties, 'utm_content'), timestamp) AS initial_utm_content,
  argMinState(JSONExtractString(properties, 'gclid'), timestamp) AS initial_gclid,
  argMinState(JSONExtractString(properties, 'gad_source'), timestamp) AS initial_gad_source,
  argMinState(JSONExtractString(properties, 'gclsrc'), timestamp) AS initial_gclsrc,
  argMinState(JSONExtractString(properties, 'dclid'), timestamp) AS initial_dclid,
  argMinState(JSONExtractString(properties, 'gbraid'), timestamp) AS initial_gbraid,
  argMinState(JSONExtractString(properties, 'wbraid'), timestamp) AS initial_wbraid,
  argMinState(JSONExtractString(properties, 'fbclid'), timestamp) AS initial_fbclid,
  argMinState(JSONExtractString(properties, 'msclkid'), timestamp) AS initial_msclkid,
  argMinState(JSONExtractString(properties, 'twclid'), timestamp) AS initial_twclid,
  argMinState(JSONExtractString(properties, 'li_fat_id'), timestamp) AS initial_li_fat_id,
  argMinState(JSONExtractString(properties, 'mc_cid'), timestamp) AS initial_mc_cid,
  argMinState(JSONExtractString(properties, 'igshid'), timestamp) AS initial_igshid,
  argMinState(JSONExtractString(properties, 'ttclid'), timestamp) AS initial_ttclid,
  argMinState(JSONExtractString(properties, 'epik'), timestamp) AS initial_epik,
  argMinState(JSONExtractString(properties, 'qclid'), timestamp) AS initial_qclid,
  argMinState(JSONExtractString(properties, 'sccid'), timestamp) AS initial_sccid,
  argMinState(JSONExtractString(properties, '_kx'), timestamp) AS initial__kx,
  argMinState(JSONExtractString(properties, 'irclid'), timestamp) AS initial_irclid,
  sumIf(1, event = '$pageview') AS pageview_count,
  uniqState(CAST(if(event = '$pageview', uuid, NULL), 'Nullable(UUID)')) AS pageview_uniq,
  sumIf(1, event = '$autocapture') AS autocapture_count,
  uniqState(CAST(if(event = '$autocapture', uuid, NULL), 'Nullable(UUID)')) AS autocapture_uniq,
  sumIf(1, event = '$screen') AS screen_count,
  uniqState(CAST(if(event = '$screen', uuid, NULL), 'Nullable(UUID)')) AS screen_uniq,
  false AS maybe_has_session_replay,
  uniqUpToState(
    1
  )(CAST(if((event = '$pageview') OR (event = '$screen') OR (event = '$autocapture'), uuid, NULL), 'Nullable(UUID)')) AS page_screen_autocapture_uniq_up_to,
  argMinState(
    accurateCastOrNull(
      replaceRegexpAll(
        nullIf(nullIf(JSONExtractRaw(properties, '$web_vitals_LCP_value'), ''), 'null'),
        '^"|"$',
        ''
      ),
      'Float64'
    ),
    timestamp
  ) AS vitals_lcp
FROM posthog.sharded_events
WHERE
  bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(`$session_id`, 'UUID')), 76), 15) = 7
GROUP BY
  team_id, toStartOfHour(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000))), cityHash64(session_id_v7), session_id_v7

# Objects only the test suite uses, such as materialized views that stand in for the kafka pipeline.

module "raw_sessions_v3_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.test && !contains(var.exclude, "raw_sessions_v3_mv")
  database = var.database
  name     = "raw_sessions_v3_mv"
  to_table = "${var.database}.writable_raw_sessions_v3"
  query    = <<-SQL
    WITH
        JSONExtract(properties, 'Tuple(\n            `$current_url` Nullable(String),\n            `$external_click_url` Nullable(String),\n            `$browser` Nullable(String),\n            `$browser_version` Nullable(String),\n            `$os` Nullable(String),\n            `$os_version` Nullable(String),\n            `$device_type` Nullable(String),\n            `$viewport_width` Nullable(Int64),\n            `$viewport_height` Nullable(Int64),\n            `$geoip_country_code` Nullable(String),\n            `$geoip_subdivision_1_code` Nullable(String),\n            `$geoip_subdivision_1_name` Nullable(String),\n            `$geoip_subdivision_city_name` Nullable(String),\n            `$geoip_time_zone` Nullable(String),\n            `$referring_domain` Nullable(String),\n            `utm_source` Nullable(String),\n            `utm_campaign` Nullable(String),\n            `utm_medium` Nullable(String),\n            `utm_term` Nullable(String),\n            `utm_content` Nullable(String),\n            `gclid` Nullable(String),\n            `gad_source` Nullable(String),\n            `fbclid` Nullable(String),\n            `$host` Nullable(String),\n            `gclsrc` Nullable(String),\n            `dclid` Nullable(String),\n            `gbraid` Nullable(String),\n            `wbraid` Nullable(String),\n            `msclkid` Nullable(String),\n            `twclid` Nullable(String),\n            `li_fat_id` Nullable(String),\n            `mc_cid` Nullable(String),\n            `igshid` Nullable(String),\n            `ttclid` Nullable(String),\n            `epik` Nullable(String),\n            `qclid` Nullable(String),\n            `sccid` Nullable(String),\n            `_kx` Nullable(String),\n            `irclid` Nullable(String)\n        )') AS p,
        JSONExtractString(person_properties, 'email') AS _person_email,
        tupleElement(p, '$current_url') AS _current_url,
        tupleElement(p, '$external_click_url') AS _external_click_url,
        tupleElement(p, '$browser') AS _browser,
        tupleElement(p, '$browser_version') AS _browser_version,
        tupleElement(p, '$os') AS _os,
        tupleElement(p, '$os_version') AS _os_version,
        tupleElement(p, '$device_type') AS _device_type,
        tupleElement(p, '$viewport_width') AS _viewport_width,
        tupleElement(p, '$viewport_height') AS _viewport_height,
        tupleElement(p, '$geoip_country_code') AS _geoip_country_code,
        tupleElement(p, '$geoip_subdivision_1_code') AS _geoip_subdivision_1_code,
        tupleElement(p, '$geoip_subdivision_1_name') AS _geoip_subdivision_1_name,
        tupleElement(p, '$geoip_subdivision_city_name') AS _geoip_subdivision_city_name,
        tupleElement(p, '$geoip_time_zone') AS _geoip_time_zone,
        tupleElement(p, '$referring_domain') AS _referring_domain,
        tupleElement(p, 'utm_source') AS _utm_source,
        tupleElement(p, 'utm_campaign') AS _utm_campaign,
        tupleElement(p, 'utm_medium') AS _utm_medium,
        tupleElement(p, 'utm_term') AS _utm_term,
        tupleElement(p, 'utm_content') AS _utm_content,
        tupleElement(p, 'gclid') AS _gclid,
        tupleElement(p, 'gad_source') AS _gad_source,
        tupleElement(p, 'fbclid') AS _fbclid,
        tupleElement(p, 'gclsrc') AS gclsrc,
        tupleElement(p, 'dclid') AS dclid,
        tupleElement(p, 'gbraid') AS gbraid,
        tupleElement(p, 'wbraid') AS wbraid,
        tupleElement(p, 'msclkid') AS msclkid,
        tupleElement(p, 'twclid') AS twclid,
        tupleElement(p, 'li_fat_id') AS li_fat_id,
        tupleElement(p, 'mc_cid') AS mc_cid,
        tupleElement(p, 'igshid') AS igshid,
        tupleElement(p, 'ttclid') AS ttclid,
        tupleElement(p, 'epik') AS epik,
        tupleElement(p, 'qclid') AS qclid,
        tupleElement(p, 'sccid') AS sccid,
        tupleElement(p, '_kx') AS _kx,
        tupleElement(p, 'irclid') AS irclid,
        CAST(mapFilter((k, v) -> (v IS NOT NULL), map('gclsrc', gclsrc, 'dclid', dclid, 'gbraid', gbraid, 'wbraid', wbraid, 'msclkid', msclkid, 'twclid', twclid, 'li_fat_id', li_fat_id, 'mc_cid', mc_cid, 'igshid', igshid, 'ttclid', ttclid, 'epik', epik, 'qclid', qclid, 'sccid', sccid, '_kx', _kx, 'irclid', irclid)), 'Map(String, String)') AS ad_ids_map,
        CAST(arrayFilter(x -> (x IS NOT NULL), [if(gclsrc IS NOT NULL, 'gclsrc', NULL), if(dclid IS NOT NULL, 'dclid', NULL), if(gbraid IS NOT NULL, 'gbraid', NULL), if(wbraid IS NOT NULL, 'wbraid', NULL), if(msclkid IS NOT NULL, 'msclkid', NULL), if(twclid IS NOT NULL, 'twclid', NULL), if(li_fat_id IS NOT NULL, 'li_fat_id', NULL), if(mc_cid IS NOT NULL, 'mc_cid', NULL), if(igshid IS NOT NULL, 'igshid', NULL), if(ttclid IS NOT NULL, 'ttclid', NULL), if(epik IS NOT NULL, 'epik', NULL), if(qclid IS NOT NULL, 'qclid', NULL), if(sccid IS NOT NULL, 'sccid', NULL), if(_kx IS NOT NULL, '_kx', NULL), if(irclid IS NOT NULL, 'irclid', NULL)]), 'Array(String)') AS ad_ids_set,
        tupleElement(p, '$host') AS _host,
        if((event = '$pageview') OR (event = '$screen'), timestamp, timestamp + toIntervalYear(1)) AS pageview_prio_timestamp_min,
        if((event = '$pageview') OR (event = '$screen'), timestamp, timestamp - toIntervalYear(1)) AS pageview_prio_timestamp_max
    SELECT
        team_id,
        `$session_id_uuid` AS session_id_v7,
        initializeAggregation('argMaxState', source_table.distinct_id, timestamp) AS distinct_id,
        initializeAggregation('groupUniqArrayState', source_table.distinct_id) AS distinct_ids,
        timestamp AS min_timestamp,
        timestamp AS max_timestamp,
        inserted_at AS max_inserted_at,
        if((_current_url IS NOT NULL) AND ((event = '$pageview') OR (event = '$screen')), [_current_url], []) AS urls,
        initializeAggregation('argMinState', _current_url, pageview_prio_timestamp_min) AS entry_url,
        initializeAggregation('argMaxState', _current_url, pageview_prio_timestamp_max) AS end_url,
        initializeAggregation('argMaxState', _external_click_url, timestamp) AS last_external_click_url,
        initializeAggregation('argMinState', _browser, timestamp) AS browser,
        initializeAggregation('argMinState', _browser_version, timestamp) AS browser_version,
        initializeAggregation('argMinState', _os, timestamp) AS os,
        initializeAggregation('argMinState', _os_version, timestamp) AS os_version,
        initializeAggregation('argMinState', _device_type, timestamp) AS device_type,
        initializeAggregation('argMinState', _viewport_width, timestamp) AS viewport_width,
        initializeAggregation('argMinState', _viewport_height, timestamp) AS viewport_height,
        initializeAggregation('argMinState', _geoip_country_code, timestamp) AS geoip_country_code,
        initializeAggregation('argMinState', _geoip_subdivision_1_code, timestamp) AS geoip_subdivision_1_code,
        initializeAggregation('argMinState', _geoip_subdivision_1_name, timestamp) AS geoip_subdivision_1_name,
        initializeAggregation('argMinState', _geoip_subdivision_city_name, timestamp) AS geoip_subdivision_city_name,
        initializeAggregation('argMinState', _geoip_time_zone, timestamp) AS geoip_time_zone,
        initializeAggregation('argMinState', _referring_domain, pageview_prio_timestamp_min) AS entry_referring_domain,
        initializeAggregation('argMinState', _utm_source, pageview_prio_timestamp_min) AS entry_utm_source,
        initializeAggregation('argMinState', _utm_campaign, pageview_prio_timestamp_min) AS entry_utm_campaign,
        initializeAggregation('argMinState', _utm_medium, pageview_prio_timestamp_min) AS entry_utm_medium,
        initializeAggregation('argMinState', _utm_term, pageview_prio_timestamp_min) AS entry_utm_term,
        initializeAggregation('argMinState', _utm_content, pageview_prio_timestamp_min) AS entry_utm_content,
        initializeAggregation('argMinState', _gclid, pageview_prio_timestamp_min) AS entry_gclid,
        initializeAggregation('argMinState', _gad_source, pageview_prio_timestamp_min) AS entry_gad_source,
        initializeAggregation('argMinState', _fbclid, pageview_prio_timestamp_min) AS entry_fbclid,
        initializeAggregation('argMinState', _gclid IS NOT NULL, pageview_prio_timestamp_min) AS entry_has_gclid,
        initializeAggregation('argMinState', _fbclid IS NOT NULL, pageview_prio_timestamp_min) AS entry_has_fbclid,
        initializeAggregation('argMinState', ad_ids_map, pageview_prio_timestamp_min) AS entry_ad_ids_map,
        initializeAggregation('argMinState', ad_ids_set, pageview_prio_timestamp_min) AS entry_ad_ids_set,
        initializeAggregation('argMinState', tuple(_utm_source, _utm_medium, _utm_campaign, _referring_domain, _gclid IS NOT NULL, _fbclid IS NOT NULL, _gad_source), pageview_prio_timestamp_min) AS entry_channel_type_properties,
        initializeAggregation('uniqExactState', if(event = '$pageview', uuid, NULL)) AS pageview_uniq,
        initializeAggregation('uniqExactState', if(event = '$autocapture', uuid, NULL)) AS autocapture_uniq,
        initializeAggregation('uniqExactState', if(event = '$screen', uuid, NULL)) AS screen_uniq,
        initializeAggregation('uniqUpToState(1)', if((event = '$pageview') OR (event = '$screen'), uuid, NULL)) AS page_screen_uniq_up_to,
        event = '$autocapture' AS has_autocapture,
        arrayMap((k, v) -> concat(k, '=', v), mapKeys(properties_group_feature_flags), mapValues(properties_group_feature_flags)) AS flag_key_values,
        mapKeys(properties_group_feature_flags) AS flag_keys,
        [event] AS event_names,
        if((_host IS NOT NULL) AND (_host != ''), [_host], []) AS hosts,
        if((_person_email IS NOT NULL) AND (_person_email != ''), [_person_email], []) AS emails,
        false AS has_replay_events
    FROM ${var.database}.sharded_events AS source_table
    WHERE (bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(`$session_id`, 'UUID')), 76), 15) = 7) AND true
  SQL
  override = try(var.overrides["raw_sessions_v3_mv"], {})

  depends_on = [
    module.writable_raw_sessions_v3,
  ]
}

module "raw_sessions_v3_recordings_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.test && !contains(var.exclude, "raw_sessions_v3_recordings_mv")
  database = var.database
  name     = "raw_sessions_v3_recordings_mv"
  to_table = "${var.database}.writable_raw_sessions_v3"
  query    = <<-SQL
    WITH
        min_first_timestamp AS timestamp,
        CAST(fromUnixTimestamp64Milli(9223372036854775), 'DateTime64(6)') AS max_ts_64,
        CAST(fromUnixTimestamp64Milli(-9223372036854775), 'DateTime64(6)') AS min_ts_64,
        CAST(NULL, 'Nullable(String)') AS null_s,
        CAST(NULL, 'Nullable(Int64)') AS null_i64,
        CAST(NULL, 'Nullable(UUID)') AS null_uuid
    SELECT
        team_id,
        toUInt128(accurateCast(session_id, 'UUID')) AS session_id_v7,
        fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80))) AS session_timestamp,
        initializeAggregation('argMaxState', source_table.distinct_id, min_ts_64) AS distinct_id,
        initializeAggregation('groupUniqArrayState', source_table.distinct_id) AS distinct_ids,
        timestamp AS min_timestamp,
        timestamp AS max_timestamp,
        fromUnixTimestamp(0) AS max_inserted_at,
        CAST([], 'Array(String)') AS urls,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_url,
        initializeAggregation('argMaxState', null_s, min_ts_64) AS end_url,
        initializeAggregation('argMaxState', null_s, min_ts_64) AS last_external_click_url,
        initializeAggregation('argMinState', null_s, max_ts_64) AS browser,
        initializeAggregation('argMinState', null_s, max_ts_64) AS browser_version,
        initializeAggregation('argMinState', null_s, max_ts_64) AS os,
        initializeAggregation('argMinState', null_s, max_ts_64) AS os_version,
        initializeAggregation('argMinState', null_s, max_ts_64) AS device_type,
        initializeAggregation('argMinState', null_i64, max_ts_64) AS viewport_width,
        initializeAggregation('argMinState', null_i64, max_ts_64) AS viewport_height,
        initializeAggregation('argMinState', null_s, max_ts_64) AS geoip_country_code,
        initializeAggregation('argMinState', null_s, max_ts_64) AS geoip_subdivision_1_code,
        initializeAggregation('argMinState', null_s, max_ts_64) AS geoip_subdivision_1_name,
        initializeAggregation('argMinState', null_s, max_ts_64) AS geoip_subdivision_city_name,
        initializeAggregation('argMinState', null_s, max_ts_64) AS geoip_time_zone,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_referring_domain,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_utm_source,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_utm_campaign,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_utm_medium,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_utm_term,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_utm_content,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_gclid,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_gad_source,
        initializeAggregation('argMinState', null_s, max_ts_64) AS entry_fbclid,
        initializeAggregation('argMinState', false, max_ts_64) AS entry_has_gclid,
        initializeAggregation('argMinState', false, max_ts_64) AS entry_has_fbclid,
        initializeAggregation('argMinState', CAST(map(), 'Map(String, String)'), max_ts_64) AS entry_ad_ids_map,
        initializeAggregation('argMinState', CAST([], 'Array(String)'), max_ts_64) AS entry_ad_ids_set,
        initializeAggregation('argMinState', tuple(null_s, null_s, null_s, null_s, false, false, null_s), max_ts_64) AS entry_channel_type_properties,
        initializeAggregation('uniqExactState', null_uuid) AS pageview_uniq,
        initializeAggregation('uniqExactState', null_uuid) AS autocapture_uniq,
        initializeAggregation('uniqExactState', null_uuid) AS screen_uniq,
        initializeAggregation('uniqUpToState(1)', null_uuid) AS page_screen_uniq_up_to,
        false AS has_autocapture,
        CAST([], 'Array(String)') AS flag_key_values,
        CAST([], 'Array(String)') AS flag_keys,
        CAST([], 'Array(String)') AS event_names,
        CAST([], 'Array(String)') AS hosts,
        CAST([], 'Array(String)') AS emails,
        true AS has_replay_events
    FROM ${var.database}.sharded_session_replay_events AS source_table
    WHERE (bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(session_id, 'UUID')), 76), 15) = 7) AND true
  SQL
  override = try(var.overrides["raw_sessions_v3_recordings_mv"], {})

  depends_on = [
    module.writable_raw_sessions_v3,
  ]
}

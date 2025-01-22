from django.conf import settings

CREATE_PERSONS_BATCH_EXPORT_VIEW = f"""
CREATE OR REPLACE VIEW persons_batch_export ON CLUSTER {settings.CLICKHOUSE_CLUSTER} AS (
    with new_persons as (
        select
            id,
            max(version) as version,
            argMax(_timestamp, person.version) AS _timestamp2
        from
            person
        where
            team_id = {{team_id:Int64}}
            and id in (
                select
                    id
                from
                    person
                where
                    team_id = {{team_id:Int64}}
                    and _timestamp >= {{interval_start:DateTime64}}
                    AND _timestamp < {{interval_end:DateTime64}}
            )
        group by
            id
        having
            (
                _timestamp2 >= {{interval_start:DateTime64}}
                AND _timestamp2 < {{interval_end:DateTime64}}
            )
    ),
    new_distinct_ids as (
        SELECT
            argMax(person_id, person_distinct_id2.version) as person_id
        from
            person_distinct_id2
        where
            team_id = {{team_id:Int64}}
            and distinct_id in (
                select
                    distinct_id
                from
                    person_distinct_id2
                where
                    team_id = {{team_id:Int64}}
                    and _timestamp >= {{interval_start:DateTime64}}
                    AND _timestamp < {{interval_end:DateTime64}}
            )
        group by
            distinct_id
        having
            (
                argMax(_timestamp, person_distinct_id2.version) >= {{interval_start:DateTime64}}
                AND argMax(_timestamp, person_distinct_id2.version) < {{interval_end:DateTime64}}
            )
    ),
    all_new_persons as (
        select
            id,
            version
        from
            new_persons
        UNION
        ALL
        select
            id,
            max(version)
        from
            person
        where
            team_id = {{team_id:Int64}}
            and id in new_distinct_ids
        group by
            id
    )
    select
        p.team_id AS team_id,
        pd.distinct_id AS distinct_id,
        toString(p.id) AS person_id,
        p.properties AS properties,
        pd.version AS person_distinct_id_version,
        p.version AS person_version,
        p.created_at AS created_at,
        multiIf(
            (
                pd._timestamp >= {{interval_start:DateTime64}}
                AND pd._timestamp < {{interval_end:DateTime64}}
            )
            AND NOT (
                p._timestamp >= {{interval_start:DateTime64}}
                AND p._timestamp < {{interval_end:DateTime64}}
            ),
            pd._timestamp,
            (
                p._timestamp >= {{interval_start:DateTime64}}
                AND p._timestamp < {{interval_end:DateTime64}}
            )
            AND NOT (
                pd._timestamp >= {{interval_start:DateTime64}}
                AND pd._timestamp < {{interval_end:DateTime64}}
            ),
            p._timestamp,
            least(p._timestamp, pd._timestamp)
        ) AS _inserted_at
    from
        person p
        INNER JOIN (
            SELECT
                distinct_id,
                max(version) AS version,
                argMax(person_id, person_distinct_id2.version) AS person_id2,
                argMax(_timestamp, person_distinct_id2.version) AS _timestamp
            FROM
                person_distinct_id2
            WHERE
                team_id = {{team_id:Int64}}
                and person_id IN (
                    select
                        id
                    from
                        all_new_persons
                )
            GROUP BY
                distinct_id
        ) AS pd ON p.id = pd.person_id2
    where
        team_id = {{team_id:Int64}}
        and (id, version) in all_new_persons
    ORDER BY
        _inserted_at
)

"""

CREATE_PERSONS_BATCH_EXPORT_VIEW_BACKFILL = f"""
CREATE OR REPLACE VIEW persons_batch_export_backfill ON CLUSTER {settings.CLICKHOUSE_CLUSTER} AS (
    SELECT
        pd.team_id AS team_id,
        pd.distinct_id AS distinct_id,
        toString(p.id) AS person_id,
        p.properties AS properties,
        pd.version AS person_distinct_id_version,
        p.version AS person_version,
        p.created_at AS created_at,
        multiIf(
            pd._timestamp < {{interval_end:DateTime64}}
                AND NOT p._timestamp < {{interval_end:DateTime64}},
            pd._timestamp,
            p._timestamp < {{interval_end:DateTime64}}
                AND NOT pd._timestamp < {{interval_end:DateTime64}},
            p._timestamp,
            least(p._timestamp, pd._timestamp)
        ) AS _inserted_at
    FROM (
        SELECT
            team_id,
            distinct_id,
            max(version) AS version,
            argMax(person_id, person_distinct_id2.version) AS person_id,
            argMax(_timestamp, person_distinct_id2.version) AS _timestamp
        FROM
            person_distinct_id2
        PREWHERE
            team_id = {{team_id:Int64}}
        GROUP BY
            team_id,
            distinct_id
    ) AS pd
    INNER JOIN (
        SELECT
            team_id,
            id,
            max(version) AS version,
            argMax(properties, person.version) AS properties,
            argMax(created_at, person.version) AS created_at,
            argMax(_timestamp, person.version) AS _timestamp
        FROM
            person
        PREWHERE
            team_id = {{team_id:Int64}}
        GROUP BY
            team_id,
            id
    ) AS p ON p.id = pd.person_id AND p.team_id = pd.team_id
    WHERE
        pd.team_id = {{team_id:Int64}}
        AND p.team_id = {{team_id:Int64}}
        AND (
            pd._timestamp < {{interval_end:DateTime64}}
            OR p._timestamp < {{interval_end:DateTime64}}
        )
    ORDER BY
        _inserted_at
)
"""

CREATE_EVENTS_BATCH_EXPORT_VIEW = f"""
CREATE OR REPLACE VIEW events_batch_export ON CLUSTER {settings.CLICKHOUSE_CLUSTER} AS (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        COALESCE(inserted_at, _timestamp) AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    PREWHERE
        COALESCE(events.inserted_at, events._timestamp) >= {{interval_start:DateTime64}}
        AND COALESCE(events.inserted_at, events._timestamp) < {{interval_end:DateTime64}}
    WHERE
        team_id = {{team_id:Int64}}
        AND events.timestamp >= {{interval_start:DateTime64}} - INTERVAL {{lookback_days:Int32}} DAY
        AND events.timestamp < {{interval_end:DateTime64}} + INTERVAL 1 DAY
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
    ORDER BY
        _inserted_at, event
    SETTINGS optimize_aggregation_in_order=1
)
"""

CREATE_EVENTS_BATCH_EXPORT_VIEW_UNBOUNDED = f"""
CREATE OR REPLACE VIEW events_batch_export_unbounded ON CLUSTER {settings.CLICKHOUSE_CLUSTER} AS (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        COALESCE(inserted_at, _timestamp) AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    PREWHERE
        COALESCE(events.inserted_at, events._timestamp) >= {{interval_start:DateTime64}}
        AND COALESCE(events.inserted_at, events._timestamp) < {{interval_end:DateTime64}}
    WHERE
        team_id = {{team_id:Int64}}
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
    ORDER BY
        _inserted_at, event
    SETTINGS optimize_aggregation_in_order=1
)
"""

CREATE_EVENTS_BATCH_EXPORT_VIEW_RECENT = f"""
CREATE OR REPLACE VIEW events_batch_export_recent ON CLUSTER {settings.CLICKHOUSE_CLUSTER} AS (
    SELECT DISTINCT ON (team_id, event, cityHash64(events_recent.distinct_id), cityHash64(events_recent.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        inserted_at AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events_recent
    PREWHERE
        events_recent.inserted_at >= {{interval_start:DateTime64}}
        AND events_recent.inserted_at < {{interval_end:DateTime64}}
    WHERE
        team_id = {{team_id:Int64}}
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
    ORDER BY
        _inserted_at, event
    SETTINGS optimize_aggregation_in_order=1
)
"""

CREATE_EVENTS_BATCH_EXPORT_VIEW_BACKFILL = f"""
CREATE OR REPLACE VIEW events_batch_export_backfill ON CLUSTER {settings.CLICKHOUSE_CLUSTER} AS (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        timestamp AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    WHERE
        team_id = {{team_id:Int64}}
        AND events.timestamp >= {{interval_start:DateTime64}}
        AND events.timestamp < {{interval_end:DateTime64}}
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
    ORDER BY
        _inserted_at, event
    SETTINGS optimize_aggregation_in_order=1
)
"""

EVENT_COUNT_BY_INTERVAL = """
SELECT
    toStartOfInterval(_inserted_at, INTERVAL {interval}) AS interval_start,
    interval_start + INTERVAL {interval} AS interval_end,
    COUNT(*) as total_count
FROM
    events_batch_export_recent(
        team_id={team_id},
        interval_start={overall_interval_start},
        interval_end={overall_interval_end},
        include_events={include_events}::Array(String),
        exclude_events={exclude_events}::Array(String)
    ) AS events
GROUP BY interval_start
ORDER BY interval_start desc
SETTINGS max_replica_delay_for_distributed_queries=1
"""

CREATE_SESSIONS_BATCH_EXPORT_VIEW = f"""
CREATE OR REPLACE VIEW sessions_batch_export ON CLUSTER {settings.CLICKHOUSE_CLUSTER} AS (
    SELECT
        team_id as team_id,
        session_id_v7 as session_id_v7,
        argMaxMerge(distinct_id) as distinct_id,
        min(min_timestamp) as min_timestamp,
        max(max_timestamp) as max_timestamp,
        max(raw_sessions.max_timestamp) as _inserted_at,

        arrayDistinct(arrayFlatten(groupArray(urls))) AS urls,
        argMinMerge(entry_url) as entry_url,
        argMaxMerge(end_url) as end_url,
        argMaxMerge(last_external_click_url) as last_external_click_url,

        argMinMerge(initial_browser) as initial_browser,
        argMinMerge(initial_browser_version) as initial_browser_version,
        argMinMerge(initial_os) as initial_os,
        argMinMerge(initial_os_version) as initial_os_version,
        argMinMerge(initial_device_type) as initial_device_type,
        argMinMerge(initial_viewport_width) as initial_viewport_width,
        argMinMerge(initial_viewport_height) as initial_viewport_height,

        argMinMerge(initial_geoip_country_code) as initial_geoip_country_code,
        argMinMerge(initial_geoip_subdivision_1_code) as initial_geoip_subdivision_1_code,
        argMinMerge(initial_geoip_subdivision_1_name) as initial_geoip_subdivision_1_name,
        argMinMerge(initial_geoip_subdivision_city_name) as initial_geoip_subdivision_city_name,
        argMinMerge(initial_geoip_time_zone) as initial_geoip_time_zone,

        argMinMerge(initial_referring_domain) as initial_referring_domain,
        argMinMerge(initial_utm_source) as initial_utm_source,
        argMinMerge(initial_utm_campaign) as initial_utm_campaign,
        argMinMerge(initial_utm_medium) as initial_utm_medium,
        argMinMerge(initial_utm_term) as initial_utm_term,
        argMinMerge(initial_utm_content) as initial_utm_content,
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

        sum(pageview_count) as pageview_count,
        uniqMerge(pageview_uniq) as pageview_uniq,
        sum(autocapture_count) as autocapture_count,
        uniqMerge(autocapture_uniq) as autocapture_uniq,
        sum(screen_count) as screen_count,
        uniqMerge(screen_uniq) as screen_uniq,

        max(maybe_has_session_replay) as maybe_has_session_replay,

        uniqUpToMerge(1)(page_screen_autocapture_uniq_up_to) as page_screen_autocapture_uniq_up_to,

        argMinMerge(vitals_lcp) as vitals_lcp
    FROM
        raw_sessions
    PREWHERE
        team_id = {{team_id:Int64}}
        AND raw_sessions.max_timestamp >= {{interval_start:DateTime64}}
        AND raw_sessions.max_timestamp < {{interval_end:DateTime64}}
    GROUP BY
        team_id, session_id_v7
    ORDER BY
        _inserted_at
)
"""


CREATE_SESSIONS_BATCH_EXPORT_VIEW_BACKFILL = f"""
CREATE OR REPLACE VIEW sessions_batch_export_backfill ON CLUSTER {settings.CLICKHOUSE_CLUSTER} AS (
    SELECT
        team_id as team_id,
        session_id_v7 as session_id_v7,
        argMaxMerge(distinct_id) as distinct_id,
        min(min_timestamp) as min_timestamp,
        max(max_timestamp) as max_timestamp,
        max(raw_sessions.max_timestamp) as _inserted_at,

        arrayDistinct(arrayFlatten(groupArray(urls))) AS urls,
        argMinMerge(entry_url) as entry_url,
        argMaxMerge(end_url) as end_url,
        argMaxMerge(last_external_click_url) as last_external_click_url,

        argMinMerge(initial_browser) as initial_browser,
        argMinMerge(initial_browser_version) as initial_browser_version,
        argMinMerge(initial_os) as initial_os,
        argMinMerge(initial_os_version) as initial_os_version,
        argMinMerge(initial_device_type) as initial_device_type,
        argMinMerge(initial_viewport_width) as initial_viewport_width,
        argMinMerge(initial_viewport_height) as initial_viewport_height,

        argMinMerge(initial_geoip_country_code) as initial_geoip_country_code,
        argMinMerge(initial_geoip_subdivision_1_code) as initial_geoip_subdivision_1_code,
        argMinMerge(initial_geoip_subdivision_1_name) as initial_geoip_subdivision_1_name,
        argMinMerge(initial_geoip_subdivision_city_name) as initial_geoip_subdivision_city_name,
        argMinMerge(initial_geoip_time_zone) as initial_geoip_time_zone,

        argMinMerge(initial_referring_domain) as initial_referring_domain,
        argMinMerge(initial_utm_source) as initial_utm_source,
        argMinMerge(initial_utm_campaign) as initial_utm_campaign,
        argMinMerge(initial_utm_medium) as initial_utm_medium,
        argMinMerge(initial_utm_term) as initial_utm_term,
        argMinMerge(initial_utm_content) as initial_utm_content,
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

        sum(pageview_count) as pageview_count,
        uniqMerge(pageview_uniq) as pageview_uniq,
        sum(autocapture_count) as autocapture_count,
        uniqMerge(autocapture_uniq) as autocapture_uniq,
        sum(screen_count) as screen_count,
        uniqMerge(screen_uniq) as screen_uniq,

        max(maybe_has_session_replay) as maybe_has_session_replay,

        uniqUpToMerge(1)(page_screen_autocapture_uniq_up_to) as page_screen_autocapture_uniq_up_to,

        argMinMerge(vitals_lcp) as vitals_lcp
    FROM
        raw_sessions
    PREWHERE
        team_id = {{team_id:Int64}}
        AND raw_sessions.max_timestamp < {{interval_end:DateTime64}}
    GROUP BY
        team_id, session_id_v7
    ORDER BY
        _inserted_at
)
"""

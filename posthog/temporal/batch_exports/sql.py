from string import Template

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.parser import parse_expr

SELECT_FROM_PERSONS_VIEW = """
SELECT
    persons.team_id AS team_id,
    persons.distinct_id AS distinct_id,
    persons.person_id AS person_id,
    persons.properties AS properties,
    persons.person_distinct_id_version AS person_distinct_id_version,
    persons.person_version AS person_version,
    persons._inserted_at AS _inserted_at
FROM
    persons_batch_export(
        team_id={team_id},
        interval_start={interval_start},
        interval_end={interval_end}
    ) AS persons
FORMAT ArrowStream
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""

# This is an updated version of the view that we will use going forward
# We will migrate each batch export destination over one at a time to migitate
# risk, and once this is done we can clean this up.
SELECT_FROM_PERSONS_VIEW_NEW = """
SELECT
    persons.team_id AS team_id,
    persons.distinct_id AS distinct_id,
    persons.person_id AS person_id,
    persons.properties AS properties,
    persons.person_distinct_id_version AS person_distinct_id_version,
    persons.person_version AS person_version,
    persons.created_at AS created_at,
    persons._inserted_at AS _inserted_at
FROM
    persons_batch_export(
        team_id={team_id},
        interval_start={interval_start},
        interval_end={interval_end}
    ) AS persons
FORMAT ArrowStream
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""

SELECT_FROM_PERSONS_VIEW_BACKFILL = """
SELECT
    persons.team_id AS team_id,
    persons.distinct_id AS distinct_id,
    persons.person_id AS person_id,
    persons.properties AS properties,
    persons.person_distinct_id_version AS person_distinct_id_version,
    persons.person_version AS person_version,
    persons._inserted_at AS _inserted_at
FROM
    persons_batch_export_backfill(
        team_id={team_id},
        interval_end={interval_end}
    ) AS persons
FORMAT ArrowStream
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""

# This is an updated version of the view that we will use going forward
# We will migrate each batch export destination over one at a time to migitate
# risk, and once this is done we can clean this up.
SELECT_FROM_PERSONS_VIEW_BACKFILL_NEW = """
SELECT
    persons.team_id AS team_id,
    persons.distinct_id AS distinct_id,
    persons.person_id AS person_id,
    persons.properties AS properties,
    persons.person_distinct_id_version AS person_distinct_id_version,
    persons.person_version AS person_version,
    persons.created_at AS created_at,
    persons._inserted_at AS _inserted_at
FROM
    persons_batch_export_backfill(
        team_id={team_id},
        interval_end={interval_end}
    ) AS persons
FORMAT ArrowStream
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""

SELECT_FROM_EVENTS_VIEW = Template(
    """
SELECT
    $fields
FROM (
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
        $filters
    ORDER BY
        _inserted_at, event
) AS events
FORMAT ArrowStream
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""
)

SELECT_FROM_EVENTS_VIEW_RECENT = Template(
    """
SELECT
    $fields
FROM (
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
        events_recent AS events
    PREWHERE
        events_recent.inserted_at >= {{interval_start:DateTime64}}
        AND events_recent.inserted_at < {{interval_end:DateTime64}}
    WHERE
        team_id = {{team_id:Int64}}
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
        $filters
    ORDER BY
        _inserted_at, event
) AS events
FORMAT ArrowStream
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    max_replica_delay_for_distributed_queries=1,
    optimize_aggregation_in_order=1
"""
)

SELECT_FROM_DISTRIBUTED_EVENTS_RECENT = Template(
    """
SELECT
    $fields
FROM (
    SELECT DISTINCT ON (team_id, event, cityHash64(distributed_events_recent.distinct_id), cityHash64(distributed_events_recent.uuid))
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
        nullIf(JSONExtractString(properties, '$$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$$set_once'), '') AS set_once
    FROM
        distributed_events_recent AS events
    PREWHERE
        distributed_events_recent.inserted_at >= {interval_start}::DateTime64
        AND distributed_events_recent.inserted_at < {interval_end}::DateTime64
    WHERE
        team_id = {team_id}::Int64
        AND (length({include_events}::Array(String)) = 0 OR event IN {include_events}::Array(String))
        AND (length({exclude_events}::Array(String)) = 0 OR event NOT IN {exclude_events}::Array(String))
        $filters
    ORDER BY
        _inserted_at, event
) AS events
FORMAT ArrowStream
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    max_replica_delay_for_distributed_queries=60,
    fallback_to_stale_replicas_for_distributed_queries=0,
    optimize_aggregation_in_order=1
"""
)


SELECT_FROM_EVENTS_VIEW_UNBOUNDED = Template(
    """
SELECT
    $fields
FROM (
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
        $filters
    ORDER BY
        _inserted_at, event
) AS events
FORMAT ArrowStream
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""
)

SELECT_FROM_EVENTS_VIEW_BACKFILL = Template(
    """
SELECT
    $fields
FROM (
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
        $filters
    ORDER BY
        _inserted_at, event
) as events
FORMAT ArrowStream
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""
)


class HogQLQueryBatchExportSettings(HogQLQuerySettings):
    optimize_aggregation_in_order: bool | None = True
    max_bytes_before_external_sort: int | None = 50000000000
    max_bytes_before_external_group_by: int | None = 50000000000


SELECT_FROM_SESSIONS_HOGQL = ast.SelectQuery(
    select=[
        parse_expr("*"),
        parse_expr("$end_timestamp as _inserted_at"),
    ],
    select_from=ast.JoinExpr(table=ast.Field(chain=["sessions"])),
    order_by=[ast.OrderExpr(expr=ast.Field(chain=["_inserted_at"]), order="ASC")],
    settings=HogQLQueryBatchExportSettings(),
)

SELECT_FROM_SESSIONS_VIEW = Template("""
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
WHERE
    $filters
GROUP BY
    team_id, session_id_v7
ORDER BY
    _inserted_at
FORMAT ArrowStream
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
""")

SELECT_FROM_SESSIONS_VIEW_BACKFILL = """
SELECT
    sessions.team_id as team_id,
    sessions.session_id_v7 as session_id_v7,
    sessions.distinct_id as distinct_id,
    sessions.min_timestamp as min_timestamp,
    sessions.max_timestamp as max_timestamp,
    sessions._inserted_at as _inserted_at,
    sessions.urls as urls,
    sessions.entry_url as entry_url,
    sessions.end_url as end_url,
    sessions.last_external_click_url as last_external_click_url,
    sessions.initial_browser as initial_browser,
    sessions.initial_browser_version as initial_browser_version,
    sessions.initial_os as initial_os,
    sessions.initial_os_version as initial_os_version,
    sessions.initial_device_type as initial_device_type,
    sessions.initial_viewport_width as initial_viewport_width,
    sessions.initial_viewport_height as initial_viewport_height,
    sessions.initial_geoip_country_code as initial_geoip_country_code,
    sessions.initial_geoip_subdivision_1_code as initial_geoip_subdivision_1_code,
    sessions.initial_geoip_subdivision_1_name as initial_geoip_subdivision_1_name,
    sessions.initial_geoip_subdivision_city_name as initial_geoip_subdivision_city_name,
    sessions.initial_geoip_time_zone as initial_geoip_time_zone,
    sessions.initial_referring_domain as initial_referring_domain,
    sessions.initial_utm_source as initial_utm_source,
    sessions.initial_utm_campaign as initial_utm_campaign,
    sessions.initial_utm_medium as initial_utm_medium,
    sessions.initial_utm_term as initial_utm_term,
    sessions.initial_utm_content as initial_utm_content,
    sessions.initial_gclid as initial_gclid,
    sessions.initial_gad_source as initial_gad_source,
    sessions.initial_gclsrc as initial_gclsrc,
    sessions.initial_dclid as initial_dclid,
    sessions.initial_gbraid as initial_gbraid,
    sessions.initial_wbraid as initial_wbraid,
    sessions.initial_fbclid as initial_fbclid,
    sessions.initial_msclkid as initial_msclkid,
    sessions.initial_twclid as initial_twclid,
    sessions.initial_li_fat_id as initial_li_fat_id,
    sessions.initial_mc_cid as initial_mc_cid,
    sessions.initial_igshid as initial_igshid,
    sessions.initial_ttclid as initial_ttclid,
    sessions.pageview_count as pageview_count,
    sessions.pageview_uniq as pageview_uniq,
    sessions.autocapture_count as autocapture_count,
    sessions.autocapture_uniq as autocapture_uniq,
    sessions.screen_count as screen_count,
    sessions.screen_uniq as screen_uniq,
    sessions.maybe_has_session_replay as maybe_has_session_replay,
    sessions.page_screen_autocapture_uniq_up_to as page_screen_autocapture_uniq_up_to,
    sessions.vitals_lcp as vitals_lcp
FROM
    sessions_batch_export_backfill(
        team_id={team_id},
        interval_end={interval_end}
    ) AS sessions
FORMAT ArrowStream
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""

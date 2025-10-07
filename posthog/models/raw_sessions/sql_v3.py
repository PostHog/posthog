from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

"""Raw sessions table v3

This is a clickhouse materialized view that aggregates events into sessions, based on the session ID.

All events with the same session ID will be aggregated into approximately one row per session ID, which can greatly
reduce the amount of data that needs to be read from disk for session-based queries.

It's not guaranteed that clickhouse will merge all events for a session into a single row, so any queries against this
table should always aggregate again on session_id (the HogQL session table will do this automatically, so HogQL users
don't need to consider this).

Upgrades over v2:
* Has a property map for storing lower-tier ad ids, making it easier to add new ad ids in the future
* Stores presence of ad ids separately from the value, so e.g. channel type calculations only need to read 1 bit instead of a gclid string up to 100 chars
* Parses JSON only once per event rather than once per column per event, saving CPU usage
* Removes a lot of deprecated fields that are no longer used
* Has a dedicated column for the channel type properties, reducing the number of times the timestamp needs to be read when calculating channel type
"""

TABLE_BASE_NAME_V3 = "raw_sessions_v3"


def DISTRIBUTED_RAW_SESSIONS_TABLE_V3():
    return TABLE_BASE_NAME_V3


def SHARDED_RAW_SESSIONS_TABLE_V3():
    return f"sharded_{TABLE_BASE_NAME_V3}"


def WRITABLE_RAW_SESSIONS_TABLE_V3():
    return f"writable_{TABLE_BASE_NAME_V3}"


def TRUNCATE_RAW_SESSIONS_TABLE_SQL_V3():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_RAW_SESSIONS_TABLE_V3()}"


def DROP_RAW_SESSION_TABLE_SQL_V3():
    return f"DROP TABLE IF EXISTS {SHARDED_RAW_SESSIONS_TABLE_V3()}"


def DROP_RAW_SESSION_DISTRIBUTED_TABLE_SQL_V3():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_RAW_SESSIONS_TABLE_V3()}"


def DROP_RAW_SESSION_WRITABLE_TABLE_SQL_V3():
    return f"DROP TABLE IF EXISTS {WRITABLE_RAW_SESSIONS_TABLE_V3()}"


def DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL_V3():
    return f"DROP TABLE IF EXISTS {TABLE_BASE_NAME_V3}_mv"


def DROP_RAW_SESSION_VIEW_SQL_V3():
    return f"DROP VIEW IF EXISTS {TABLE_BASE_NAME_V3}_v"


# if updating these column definitions
# you'll need to update the explicit column definitions in the materialized view creation statement below
RAW_SESSIONS_TABLE_BASE_SQL_V3 = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,

    -- Both UInt128 and UUID are imperfect choices here
    -- see https://michcioperz.com/wiki/clickhouse-uuid-ordering/
    -- but also see https://github.com/ClickHouse/ClickHouse/issues/77226 and hope
    -- right now choose UInt128 as that's the type of events.$session_id_uuid, but in the future we will probably want to switch everything to the new CH UUID type (when it's released)
    session_id_v7 UInt128,
    -- Ideally we would not need to store this separately, as the ID *is* the timestamp
    -- Unfortunately for now, chaining clickhouse functions to extract the timestamp will break indexes / partition pruning, so do this workaround
    -- again, when the new CH UUID type is released, we should try to switch to that and remove the separate timestamp column
    session_timestamp DateTime64 MATERIALIZED fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80))),

    -- ClickHouse will pick the latest value of distinct_id for the session
    -- this is fine since even if the distinct_id changes during a session
    distinct_id AggregateFunction(argMax, String, DateTime64(6, 'UTC')),
    person_id AggregateFunction(argMax, UUID, DateTime64(6, 'UTC')),
    distinct_ids AggregateFunction(groupUniqArray, String),

    min_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    max_inserted_at SimpleAggregateFunction(max, DateTime64(6, 'UTC')),

    -- urls
    urls SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    entry_url AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    end_url AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC')),
    last_external_click_url AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC')),

    -- device
    browser AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    browser_version AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    os AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    os_version AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    device_type AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    viewport_width AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC')),
    viewport_height AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC')),

    -- geoip
    -- only store the properties we actually use, as there's tons, see https://posthog.com/docs/cdp/geoip-enrichment
    geoip_country_code AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_subdivision_1_code AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_subdivision_1_name AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_subdivision_city_name AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_time_zone AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),

    -- attribution
    entry_referring_domain AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_source AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_campaign AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_medium AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_term AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_content AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_gclid AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_gad_source AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_fbclid AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),

    -- for channel type calculation, it's enough to know if these were present
    entry_has_gclid AggregateFunction(argMin, Boolean, DateTime64(6, 'UTC')),
    entry_has_fbclid AggregateFunction(argMin, Boolean, DateTime64(6, 'UTC')),

    -- for lower-tier ad ids, just put them in a map, and set of the ones present
    entry_ad_ids_map AggregateFunction(argMin, Map(String, String), DateTime64(6, 'UTC')),
    entry_ad_ids_set AggregateFunction(argMin, Array(String), DateTime64(6, 'UTC')),

    -- channel type properties tuple - to reduce redundant reading of the timestamp when loading all of these columns
    -- utm_source, utm_medium, utm_campaign, referring domain, has_gclid, has_fbclid, gad_source
    entry_channel_type_properties AggregateFunction(argMin, Tuple(Nullable(String), Nullable(String), Nullable(String), Nullable(String), Boolean, Boolean, Nullable(String)), DateTime64(6, 'UTC')),

    -- Count pageview, autocapture, and screen events for providing totals.
    -- Use uniqExact instead of count, so that inserting events can be idempotent. This is necessary as sometimes we see
    -- events being inserted multiple times to be deduped later, but that can trigger multiple rows here.
    -- Additionally, idempotency is useful for backfilling, as we can just reinsert the same events without worrying.
    pageview_uniq AggregateFunction(uniqExact, Nullable(UUID)),
    autocapture_uniq AggregateFunction(uniqExact, Nullable(UUID)),
    screen_uniq AggregateFunction(uniqExact, Nullable(UUID)),

    -- As a performance optimisation, also keep track of the uniq events for all of these combined.
    -- This is a much more efficient way of calculating the bounce rate, as >2 means not a bounce
    page_screen_autocapture_uniq_up_to AggregateFunction(uniqUpTo(1), Nullable(UUID)),

    -- Flags - store every seen value for each flag
    flag_values AggregateFunction(groupUniqArrayMap, Map(String, String))
) ENGINE = {engine}
"""


def RAW_SESSIONS_DATA_TABLE_ENGINE_V3():
    return AggregatingMergeTree(TABLE_BASE_NAME_V3, replication_scheme=ReplicationScheme.SHARDED)


def RAW_SESSIONS_TABLE_SQL_V3():
    return (
        RAW_SESSIONS_TABLE_BASE_SQL_V3
        + """
PARTITION BY toYYYYMM(session_timestamp)
ORDER BY (
    team_id,
    session_timestamp,
    session_id_v7
)
"""
    ).format(
        table_name=SHARDED_RAW_SESSIONS_TABLE_V3(),
        engine=RAW_SESSIONS_DATA_TABLE_ENGINE_V3(),
    )


SESSION_V3_LOWER_TIER_AD_IDS = [
    "gclsrc",
    "dclid",
    "gbraid",
    "wbraid",
    "msclkid",
    "twclid",
    "li_fat_id",
    "mc_cid",
    "igshid",
    "ttclid",
    "epik",
    "qclid",
    "sccid",
    "_kx",
    "irclid",
]

new_line = "\n"

# See https://kb.altinity.com/altinity-kb-queries-and-syntax/jsonextract-to-parse-many-attributes-at-a-time/
# Or https://posthog.slack.com/archives/C02JQ320FV3/p1721406540313379?thread_ts=1721334861.073739&cid=C02JQ320FV3
PROPERTIES = f"""
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
{f',{new_line}'.join([f'            `{ad_id}` Nullable(String)' for ad_id in SESSION_V3_LOWER_TIER_AD_IDS])}
        )') as p,
        tupleElement(p, '$current_url') as current_url,
        tupleElement(p, '$external_click_url') as external_click_url,
        tupleElement(p, '$browser') as browser,
        tupleElement(p, '$browser_version') as browser_version,
        tupleElement(p, '$os') as os,
        tupleElement(p, '$os_version') as os_version,
        tupleElement(p, '$device_type') as device_type,
        tupleElement(p, '$viewport_width') as viewport_width,
        tupleElement(p, '$viewport_height') as viewport_height,
        tupleElement(p, '$geoip_country_code') as geoip_country_code,
        tupleElement(p, '$geoip_subdivision_1_code') as geoip_subdivision_1_code,
        tupleElement(p, '$geoip_subdivision_1_name') as geoip_subdivision_1_name,
        tupleElement(p, '$geoip_subdivision_city_name') as geoip_subdivision_city_name,
        tupleElement(p, '$geoip_time_zone') as geoip_time_zone,
        tupleElement(p, '$referring_domain') as referring_domain,
        tupleElement(p, 'utm_source') as utm_source,
        tupleElement(p, 'utm_campaign') as utm_campaign,
        tupleElement(p, 'utm_medium') as utm_medium,
        tupleElement(p, 'utm_term') as utm_term,
        tupleElement(p, 'utm_content') as utm_content,
        tupleElement(p, 'gclid') as gclid,
        tupleElement(p, 'gad_source') as gad_source,
        tupleElement(p, 'fbclid') as fbclid,
{f',{new_line}'.join([f"        tupleElement(p, '{ad_id}') as {ad_id}" for ad_id in SESSION_V3_LOWER_TIER_AD_IDS])},
        CAST(mapFilter((k, v) -> v IS NOT NULL, map(
{f',{new_line}'.join([f"            '{ad_id}', {ad_id}" for ad_id in SESSION_V3_LOWER_TIER_AD_IDS])}
        )) AS Map(String, String)) as ad_ids_map,
        CAST(arrayFilter(x -> x IS NOT NULL, [
{f',{new_line}'.join([f"            if({ad_id} IS NOT NULL, '{ad_id}', NULL)" for ad_id in SESSION_V3_LOWER_TIER_AD_IDS])}
        ]) AS Array(String)) as ad_ids_set"""


def RAW_SESSION_TABLE_MV_SELECT_SQL_V3(where="TRUE"):
    return """
WITH parsed_events AS (
    SELECT
        team_id,
        `$session_id_uuid` AS session_id_v7,
        distinct_id AS _distinct_id,
        person_id,
        timestamp,
        inserted_at,
        event,
        uuid,
        {PROPERTIES},
        -- attribution properties from non-pageview/screen events should be deprioritized, so make the timestamp +/- 1 year so they sort last
        if (event = '$pageview' OR event = '$screen', timestamp, timestamp + toIntervalYear(1)) as pageview_prio_timestamp_min,
        if (event = '$pageview' OR event = '$screen', timestamp, timestamp - toIntervalYear(1)) as pageview_prio_timestamp_max,
        properties_group_feature_flags
    FROM {database}.sharded_events
    WHERE bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(`$session_id`, 'UUID')), 76), 0xF) == 7 -- has a session id and is valid uuidv7
    AND {where}
)

SELECT
    team_id,
    session_id_v7,

    initializeAggregation('argMaxState', _distinct_id, timestamp) as distinct_id,
    initializeAggregation('argMaxState', person_id, timestamp) as person_id,
    initializeAggregation('groupUniqArrayState', _distinct_id) as distinct_ids,

    timestamp AS min_timestamp,
    timestamp AS max_timestamp,
    inserted_at AS max_inserted_at,

    -- urls - only update if the event is a pageview or screen
    if(current_url IS NOT NULL AND (event = '$pageview' OR event = '$screen'), [current_url], []) AS urls,
    initializeAggregation('argMinState', current_url, pageview_prio_timestamp_min) as entry_url,
    initializeAggregation('argMaxState', current_url, pageview_prio_timestamp_max) as end_url,
    initializeAggregation('argMaxState', external_click_url, timestamp) as last_external_click_url,

    -- device
    initializeAggregation('argMinState', browser, timestamp) as browser,
    initializeAggregation('argMinState', browser_version, timestamp) as browser_version,
    initializeAggregation('argMinState', os, timestamp) as os,
    initializeAggregation('argMinState', os_version, timestamp) as os_version,
    initializeAggregation('argMinState', device_type, timestamp) as device_type,
    initializeAggregation('argMinState', viewport_width, timestamp) as viewport_width,
    initializeAggregation('argMinState', viewport_height, timestamp) as viewport_height,

    -- geo ip
    initializeAggregation('argMinState', geoip_country_code, timestamp) as geoip_country_code,
    initializeAggregation('argMinState', geoip_subdivision_1_code, timestamp) as geoip_subdivision_1_code,
    initializeAggregation('argMinState', geoip_subdivision_1_name, timestamp) as geoip_subdivision_1_name,
    initializeAggregation('argMinState', geoip_subdivision_city_name, timestamp) as geoip_subdivision_city_name,
    initializeAggregation('argMinState', geoip_time_zone, timestamp) as geoip_time_zone,

    -- attribution
    initializeAggregation('argMinState', referring_domain, pageview_prio_timestamp_min) as entry_referring_domain,
    initializeAggregation('argMinState', utm_source, pageview_prio_timestamp_min) as entry_utm_source,
    initializeAggregation('argMinState', utm_campaign, pageview_prio_timestamp_min) as entry_utm_campaign,
    initializeAggregation('argMinState', utm_medium, pageview_prio_timestamp_min) as entry_utm_medium,
    initializeAggregation('argMinState', utm_term, pageview_prio_timestamp_min) as entry_utm_term,
    initializeAggregation('argMinState', utm_content, pageview_prio_timestamp_min) as entry_utm_content,
    initializeAggregation('argMinState', gclid, pageview_prio_timestamp_min) as entry_gclid,
    initializeAggregation('argMinState', gad_source, pageview_prio_timestamp_min) as entry_gad_source,
    initializeAggregation('argMinState', fbclid, pageview_prio_timestamp_min) as entry_fbclid,

    -- has gclid/fbclid for reading fewer bytes when calculating channel type
    initializeAggregation('argMinState', gclid IS NOT NULL, pageview_prio_timestamp_min) as entry_has_gclid,
    initializeAggregation('argMinState', fbclid IS NOT NULL, pageview_prio_timestamp_min) as entry_has_fbclid,

    -- other ad ids
    initializeAggregation('argMinState', ad_ids_map, pageview_prio_timestamp_min) as entry_ad_ids_map,
    initializeAggregation('argMinState', ad_ids_set, pageview_prio_timestamp_min) as entry_ad_ids_set,

    -- channel type
    initializeAggregation('argMinState', tuple(utm_source, utm_medium, utm_campaign, referring_domain, gclid IS NOT NULL, fbclid IS NOT NULL, gad_source), pageview_prio_timestamp_min) as entry_channel_type_properties,


    -- counts
    initializeAggregation('uniqExactState', if(event='$pageview', uuid, NULL)) as pageview_uniq,
    initializeAggregation('uniqExactState', if(event='$autocapture', uuid, NULL)) as autocapture_uniq,
    initializeAggregation('uniqExactState', if(event='$screen', uuid, NULL)) as screen_uniq,

    -- perf
    initializeAggregation('uniqUpToState(1)', if(event='$pageview' OR event='$screen' OR event='$autocapture', uuid, NULL)) as page_screen_autocapture_uniq_up_to,

    --flags
    initializeAggregation('groupUniqArrayMapState', properties_group_feature_flags) as flag_values
FROM parsed_events
    """.format(
        database=settings.CLICKHOUSE_DATABASE,
        where=where,
        PROPERTIES=PROPERTIES,
    )


def RAW_SESSIONS_TABLE_MV_SQL_V3(where=True):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {table_name}
TO {database}.{target_table}
AS
{select_sql}
""".format(
        table_name=f"{TABLE_BASE_NAME_V3}_mv",
        target_table=WRITABLE_RAW_SESSIONS_TABLE_V3(),
        database=settings.CLICKHOUSE_DATABASE,
        select_sql=RAW_SESSION_TABLE_MV_SELECT_SQL_V3(where),
    )


RAW_SESSION_TABLE_UPDATE_SQL_V3 = (
    lambda: """
ALTER TABLE {table_name}
MODIFY QUERY
{select_sql}
""".format(
        table_name=f"{TABLE_BASE_NAME_V3}_mv",
        select_sql=RAW_SESSION_TABLE_MV_SELECT_SQL_V3(),
    )
)


def RAW_SESSION_TABLE_BACKFILL_SQL_V3(where="TRUE"):
    return """
INSERT INTO {database}.{writable_table}
{select_sql}
""".format(
        database=settings.CLICKHOUSE_DATABASE,
        writable_table=WRITABLE_RAW_SESSIONS_TABLE_V3(),
        select_sql=RAW_SESSION_TABLE_MV_SELECT_SQL_V3(where=where),
    )


# Distributed engine tables are only created if CLICKHOUSE_REPLICATED

# This table is responsible for writing to sharded_sessions based on a sharding key.


def WRITABLE_RAW_SESSIONS_TABLE_SQL_V3():
    return RAW_SESSIONS_TABLE_BASE_SQL_V3.format(
        table_name=WRITABLE_RAW_SESSIONS_TABLE_V3(),
        engine=Distributed(
            data_table=SHARDED_RAW_SESSIONS_TABLE_V3(),
            # shard via session_id so that all events for a session are on the same shard
            sharding_key="cityHash64(session_id_v7)",
        ),
    )


# This table is responsible for reading from sessions on a cluster setting


def DISTRIBUTED_RAW_SESSIONS_TABLE_SQL_V3():
    return RAW_SESSIONS_TABLE_BASE_SQL_V3.format(
        table_name=DISTRIBUTED_RAW_SESSIONS_TABLE_V3(),
        engine=Distributed(
            data_table=SHARDED_RAW_SESSIONS_TABLE_V3(),
            sharding_key="cityHash64(session_id_v7)",
        ),
    )


# This is the view that can be queried directly, that handles aggregation of potentially multiple rows per session.
# Most queries won't use this directly as they will want to pre-filter rows before aggregation, but it's useful for
# debugging
RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL_V3 = (
    lambda: f"""
CREATE OR REPLACE VIEW {TABLE_BASE_NAME_V3}_v AS
SELECT
    session_id_v7,
    session_timestamp,
    team_id,

    argMaxMerge(distinct_id) as distinct_id,
    argMaxMerge(person_id) as person_id,
    groupUniqArrayMerge(distinct_ids) AS distinct_ids,

    min(min_timestamp) as min_timestamp,
    max(max_timestamp) as max_timestamp,
    max(max_inserted_at) as max_inserted_at,

    -- urls
    arrayDistinct(arrayFlatten(groupArray(urls))) AS urls,
    argMinMerge(entry_url) as entry_url,
    argMaxMerge(end_url) as end_url,
    argMaxMerge(last_external_click_url) as last_external_click_url,

    -- device
    argMinMerge(browser) as browser,
    argMinMerge(browser_version) as browser_version,
    argMinMerge(os) as os,
    argMinMerge(os_version) as os_version,
    argMinMerge(device_type) as device_type,
    argMinMerge(viewport_width) as viewport_width,
    argMinMerge(viewport_height) as viewport_height,

    -- geoip
    argMinMerge(geoip_country_code) as geoip_country_code,
    argMinMerge(geoip_subdivision_1_code) as geoip_subdivision_1_code,
    argMinMerge(geoip_subdivision_1_name) as geoip_subdivision_1_name,
    argMinMerge(geoip_subdivision_city_name) as geoip_subdivision_city_name,
    argMinMerge(geoip_time_zone) as geoip_time_zone,

    -- attribution
    argMinMerge(entry_utm_source) as entry_utm_source,
    argMinMerge(entry_utm_campaign) as entry_utm_campaign,
    argMinMerge(entry_utm_medium) as entry_utm_medium,
    argMinMerge(entry_utm_term) as entry_utm_term,
    argMinMerge(entry_utm_content) as entry_utm_content,
    argMinMerge(entry_referring_domain) as entry_referring_domain,
    argMinMerge(entry_gclid) as entry_gclid,
    argMinMerge(entry_gad_source) as entry_gad_source,
    argMinMerge(entry_fbclid) as entry_fbclid,

    argMinMerge(entry_has_gclid) as entry_has_gclid,
    argMinMerge(entry_has_fbclid) as entry_has_fbclid,

    argMinMerge(entry_ad_ids_map) as entry_ad_ids_map,
    argMinMerge(entry_ad_ids_set) as entry_ad_ids_set,

    argMinMerge(entry_channel_type_properties) as entry_channel_type_properties,

    -- counts
    uniqExactMerge(pageview_uniq) as pageview_uniq,
    uniqExactMerge(autocapture_uniq) as autocapture_uniq,
    uniqExactMerge(screen_uniq) as screen_uniq,

    -- perf
    uniqUpToMerge(1)(page_screen_autocapture_uniq_up_to) as page_screen_autocapture_uniq_up_to,

    -- flags
    groupUniqArrayMapMerge(flag_values) as flag_values
FROM {settings.CLICKHOUSE_DATABASE}.{DISTRIBUTED_RAW_SESSIONS_TABLE_V3()}
GROUP BY session_id_v7, session_timestamp, team_id
"""
)

RAW_SELECT_SESSION_PROP_STRING_VALUES_SQL_V3 = """
SELECT
    value,
    count(value)
FROM (
    SELECT
        {property_expr} as value
    FROM
        raw_sessions_v3
    WHERE
        team_id = %(team_id)s AND
        {property_expr} IS NOT NULL AND
        {property_expr} != ''
    ORDER BY session_id_v7 DESC
    LIMIT 100000
)
GROUP BY value
ORDER BY count(value) DESC
LIMIT 20
"""

RAW_SELECT_SESSION_PROP_STRING_VALUES_SQL_WITH_FILTER_V3 = """
SELECT
    value,
    count(value)
FROM (
    SELECT
        {property_expr} as value
    FROM
        raw_sessions_v3
    WHERE
        team_id = %(team_id)s AND
        {property_expr} ILIKE %(value)s
    ORDER BY session_id_v7 DESC
    LIMIT 100000
)
GROUP BY value
ORDER BY count(value) DESC
LIMIT 20
"""

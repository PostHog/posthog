"""
Sessions on events refers to copying session data into the events table.

We use an "overrides" model, which means that we get most of the sessions on events data from the events table, but if
a row exists in this table, we use that instead.

We will have a background job in dagster which will copy data from the sessions overrides table onto the events table,
and then delete those rows from the overrides table. At query time, this is faster than if we joined against the
sessions table directly, because there will be a lot less data in the overrides table.

This table should match the schema of the sessions table exactly, the only difference is that data will be deleted from
it as part of the process of updating the events table. This update and deletion process is known as "squashing".

Sessions overrides squashing is much simpler than person overrides squashing, this is for a few reasons
* We guarantee that sessions are always contained with a 24 hour period
* We don't have to worry about person merges, sessions are independent of each other
* We can use clickhouse's intermediate state types to make life easier for us
"""
from posthog import settings
from posthog.clickhouse.table_engines import Distributed
from posthog.models.raw_sessions.sessions_v3 import SESSION_V3_LOWER_TIER_AD_IDS

TABLE_BASE_NAME_V3 = "raw_sessions_overrides_v3"


def DISTRIBUTED_RAW_SESSIONS_OVERRIDES_TABLE_V3():
    return TABLE_BASE_NAME_V3


def SHARDED_RAW_SESSIONS_OVERRIDES_TABLE_V3():
    return f"sharded_{TABLE_BASE_NAME_V3}"


def WRITABLE_RAW_SESSIONS_OVERRIDES_TABLE_V3():
    return f"writable_{TABLE_BASE_NAME_V3}"


def TRUNCATE_RAW_SESSIONS_OVERRIDES_TABLE_SQL_V3():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_RAW_SESSIONS_OVERRIDES_TABLE_V3()}"


def DROP_RAW_SESSIONS_OVERRIDES_SHARDED_TABLE_SQL_V3():
    # sync is added when dropping the sharded table, see https://posthog.slack.com/archives/C076R4753Q8/p1760696004214289?thread_ts=1760695175.656789&cid=C076R4753Q8
    return f"DROP TABLE IF EXISTS {SHARDED_RAW_SESSIONS_OVERRIDES_TABLE_V3()} SYNC"


def DROP_RAW_SESSIONS_OVERRIDES_DISTRIBUTED_TABLE_SQL_V3():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_RAW_SESSIONS_OVERRIDES_TABLE_V3()}"


def DROP_RAW_SESSIONS_OVERRIDES_WRITABLE_TABLE_SQL_V3():
    return f"DROP TABLE IF EXISTS {WRITABLE_RAW_SESSIONS_OVERRIDES_TABLE_V3()}"


def DROP_RAW_SESSIONS_OVERRIDES_MATERIALIZED_VIEW_SQL_V3():
    return f"DROP TABLE IF EXISTS {TABLE_BASE_NAME_V3}_mv"


def DROP_RAW_SESSIONS_OVERRIDES_VIEW_SQL_V3():
    return f"DROP VIEW IF EXISTS {TABLE_BASE_NAME_V3}_v"


# this should be a subset of sessions_v3 - with some things removed if they are not currently used, or only used in niche cases which wouldn't benefit from sessions-on-events
RAW_SESSIONS_OVERRIDES_TABLE_BASE_SQL_V3 = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    session_id_v7 UInt128,
    session_timestamp DateTime64 MATERIALIZED fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80))),
    min_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    max_inserted_at SimpleAggregateFunction(max, DateTime64(6, 'UTC')),

    -- urls
    entry_url AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    end_url AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC')),
    last_external_click_url AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC')),

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

    -- bounce rate
    page_screen_autocapture_uniq_up_to AggregateFunction(uniqUpTo(1), Nullable(UUID))
) ENGINE = {engine}
"""

new_line = "\n"

# See https://kb.altinity.com/altinity-kb-queries-and-syntax/jsonextract-to-parse-many-attributes-at-a-time/
# Or https://posthog.slack.com/archives/C02JQ320FV3/p1721406540313379?thread_ts=1721334861.073739&cid=C02JQ320FV3
# if updating these, you'll want to make a migration to update the MV. Also update the sessions-on-events + overrides
PROPERTIES = f"""
        JSONExtract(properties, 'Tuple(
            `$current_url` Nullable(String),
            `$external_click_url` Nullable(String),
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
        tupleElement(p, '$current_url') as _current_url,
        tupleElement(p, '$external_click_url') as _external_click_url,
        tupleElement(p, '$referring_domain') as _referring_domain,
        tupleElement(p, 'utm_source') as _utm_source,
        tupleElement(p, 'utm_campaign') as _utm_campaign,
        tupleElement(p, 'utm_medium') as _utm_medium,
        tupleElement(p, 'utm_term') as _utm_term,
        tupleElement(p, 'utm_content') as _utm_content,
        tupleElement(p, 'gclid') as _gclid,
        tupleElement(p, 'gad_source') as _gad_source,
        tupleElement(p, 'fbclid') as _fbclid,
{f',{new_line}'.join([f"        tupleElement(p, '{ad_id}') as {ad_id}" for ad_id in SESSION_V3_LOWER_TIER_AD_IDS])},
        CAST(mapFilter((k, v) -> v IS NOT NULL, map(
{f',{new_line}'.join([f"            '{ad_id}', {ad_id}" for ad_id in SESSION_V3_LOWER_TIER_AD_IDS])}
        )) AS Map(String, String)) as ad_ids_map,
        CAST(arrayFilter(x -> x IS NOT NULL, [
{f',{new_line}'.join([f"            if({ad_id} IS NOT NULL, '{ad_id}', NULL)" for ad_id in SESSION_V3_LOWER_TIER_AD_IDS])}
        ]) AS Array(String)) as ad_ids_set"""


def RAW_SESSIONS_OVERRIDES_TABLE_MV_SELECT_SQL_V3(where="TRUE"):
    return """
WITH
    {PROPERTIES},
    -- attribution properties from non-pageview/screen events should be deprioritized, so make the timestamp +/- 1 year so they sort last
    if (event = '$pageview' OR event = '$screen', timestamp, timestamp + toIntervalYear(1)) as pageview_prio_timestamp_min,
    if (event = '$pageview' OR event = '$screen', timestamp, timestamp - toIntervalYear(1)) as pageview_prio_timestamp_max
SELECT
    team_id,
    `$session_id_uuid` AS session_id_v7,

    timestamp AS min_timestamp,
    timestamp AS max_timestamp,
    inserted_at AS max_inserted_at,

    -- urls
    initializeAggregation('argMinState', _current_url, pageview_prio_timestamp_min) as entry_url,
    initializeAggregation('argMaxState', _current_url, pageview_prio_timestamp_max) as end_url,
    initializeAggregation('argMaxState', _external_click_url, timestamp) as last_external_click_url,

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

    -- perf
    initializeAggregation('uniqUpToState(1)', if(event='$pageview' OR event='$screen' OR event='$autocapture', uuid, NULL)) as page_screen_autocapture_uniq_up_to
FROM {database}.sharded_events
WHERE bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(`$session_id`, 'UUID')), 76), 0xF) == 7 -- has a session id and is valid uuidv7
AND {where}
    """.format(
        database=settings.CLICKHOUSE_DATABASE,
        where=where,
        PROPERTIES=PROPERTIES,
    )



def RAW_SESSIONS_OVERRIDES_TABLE_MV_SQL_V3(where="TRUE"):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {table_name}
TO {database}.{target_table}
AS
{select_sql}
""".format(
        table_name=f"{TABLE_BASE_NAME_V3}_mv",
        target_table=WRITABLE_RAW_SESSIONS_OVERRIDES_TABLE_V3(),
        database=settings.CLICKHOUSE_DATABASE,
        select_sql=RAW_SESSIONS_OVERRIDES_TABLE_MV_SELECT_SQL_V3(where),
    )


RAW_SESSION_TABLE_UPDATE_SQL_V3 = (
    lambda: """
ALTER TABLE {table_name}
MODIFY QUERY
{select_sql}
""".format(
        table_name=f"{TABLE_BASE_NAME_V3}_mv",
        select_sql=RAW_SESSIONS_OVERRIDES_TABLE_MV_SELECT_SQL_V3(),
    )
)


def RAW_SESSION_TABLE_BACKFILL_SQL_V3(where="TRUE"):
    return """
INSERT INTO {database}.{writable_table}
{select_sql}
""".format(
        database=settings.CLICKHOUSE_DATABASE,
        writable_table=WRITABLE_RAW_SESSIONS_OVERRIDES_TABLE_V3(),
        select_sql=RAW_SESSIONS_OVERRIDES_TABLE_MV_SELECT_SQL_V3(where=where),
    )

def WRITABLE_RAW_SESSIONS_OVERRIDES_TABLE_SQL_V3():
    return RAW_SESSIONS_OVERRIDES_TABLE_BASE_SQL_V3.format(
        table_name=WRITABLE_RAW_SESSIONS_OVERRIDES_TABLE_V3(),
        engine=Distributed(
            data_table=SHARDED_RAW_SESSIONS_OVERRIDES_TABLE_V3(),
            # shard via session_id so that all events for a session are on the same shard
            sharding_key="cityHash64(session_id_v7)",
        ),
    )


def DISTRIBUTED_RAW_SESSIONS_OVERRIDES_TABLE_SQL_V3():
    return RAW_SESSIONS_OVERRIDES_TABLE_BASE_SQL_V3.format(
        table_name=DISTRIBUTED_RAW_SESSIONS_OVERRIDES_TABLE_V3(),
        engine=Distributed(
            data_table=SHARDED_RAW_SESSIONS_OVERRIDES_TABLE_V3(),
            sharding_key="cityHash64(session_id_v7)",
        ),
    )

# this view isn't used in production, but it's very useful for testing, and there's almost no overhead to keeping it around
RAW_SESSIONS_OVERRIDES_CREATE_OR_REPLACE_VIEW_SQL_V3 = (
    lambda: f"""
CREATE OR REPLACE VIEW {TABLE_BASE_NAME_V3}_v AS
SELECT
    session_id_v7,
    session_timestamp,
    team_id,

    min(min_timestamp) as min_timestamp,
    max(max_timestamp) as max_timestamp,
    max(max_inserted_at) as max_inserted_at,

    -- urls
    argMinMerge(entry_url) as entry_url,
    argMaxMerge(end_url) as end_url,
    argMaxMerge(last_external_click_url) as last_external_click_url,

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

    -- perf
    uniqUpToMerge(1)(page_screen_autocapture_uniq_up_to) as page_screen_autocapture_uniq_up_to,
FROM {settings.CLICKHOUSE_DATABASE}.{DISTRIBUTED_RAW_SESSIONS_OVERRIDES_TABLE_V3()}
GROUP BY session_id_v7, session_timestamp, team_id
"""
)

RAW_SESSION_OVERRIDES_SQUASH_


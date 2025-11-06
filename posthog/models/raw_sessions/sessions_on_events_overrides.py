"""
Sessions on events refers to copying session data into the events table.

We use an "overrides" model, which means that we get most of the sessions on events data from the events table, but if
a row exists in this table, we use that instead.

We will have a background job in dagster which will copy data from the sessions overrides table onto the events table,
and then delete those rows from the overrides table. At query time, this is faster than if we joined against the
sessions table directly, because the overrides table will be much smaller than the sessions table, so the right hand
side of the join is much smaller.

The actual squashing process happens with these steps:
1. Create a temporary snapshot table
2. Copy the data from the overrides table into the snapshot. Group by session ID so we have one row per session (unlike the overrides table which might not have been part-merged yet).
3. Create a dictionary on top of the snapshot table
4. Use the dictionary to update the events table
5. Delete rows from the overrides table which have been squashed (based on the max_inserted_at timestamp)
6. Clean up resources (delete the snapshot table and dictionary)
"""

from posthog import settings
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.models.event.sql import EVENTS_DATA_TABLE
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


# this should be a subset of sessions_v3, in general include things that are
# * used in many queries (e.g. attribution fields or required for the bounce rate)
# and don't include things that are
# * too large (in terms of disk space) - this excludes the session feature flags, and session urls
# * not currently used in queries
RAW_SESSIONS_OVERRIDES_TABLE_BASE_SQL_V3 = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    session_id_v7 UInt128,

    session_timestamp DateTime64 MATERIALIZED fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80))),
    min_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    pageview_prio_timestamp_min SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    pageview_prio_timestamp_max SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    max_inserted_at SimpleAggregateFunction(max, DateTime64(6, 'UTC')),

    -- urls
    has_pageview_or_screen SimpleAggregateFunction(max, Boolean), -- this makes it not a subset of the sessions table, but is needed to handle url logic
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
    page_screen_autocapture_uniq_up_to AggregateFunction(groupUniqArray(2), Nullable(UUID)),

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
    {PROPERTIES}
SELECT
    team_id,
    `$session_id_uuid` AS session_id_v7,

    timestamp AS min_timestamp,
    timestamp AS max_timestamp,
    -- attribution properties from non-pageview/screen events should be deprioritized, so make the timestamp +/- 1 year so they sort last
    if (event = '$pageview' OR event = '$screen', timestamp, timestamp + toIntervalYear(1)) as pageview_prio_timestamp_min,
    if (event = '$pageview' OR event = '$screen', timestamp, timestamp - toIntervalYear(1)) as pageview_prio_timestamp_max,
    inserted_at AS max_inserted_at,

    -- urls
    (event = '$pageview' OR event = '$screen') as has_pageview_or_screen,
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
    initializeAggregation('groupUniqArrayState(2)', if(event='$pageview' OR event='$screen' OR event='$autocapture', uuid, NULL)) as page_screen_autocapture_uniq_up_to
FROM {database}.sharded_events
WHERE bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(`$session_id`, 'UUID')), 76), 0xF) == 7 -- has a session id and is valid uuidv7
AND {where}
    """.format(
        database=settings.CLICKHOUSE_DATABASE,
        where=where,
        PROPERTIES=PROPERTIES,
    )


def SHARDED_RAW_SESSION_OVERRIDES_DATA_TABLE_ENGINE_V3():
    return AggregatingMergeTree(TABLE_BASE_NAME_V3, replication_scheme=ReplicationScheme.SHARDED)


def SHARDED_RAW_SESSION_OVERRIDES_TABLE_SQL_V3():
    return (
        RAW_SESSIONS_OVERRIDES_TABLE_BASE_SQL_V3
        + """
PARTITION BY toYYYYMM(session_timestamp)
ORDER BY (
    team_id,
    session_timestamp,
    session_id_v7
)
"""
    ).format(
        table_name=SHARDED_RAW_SESSIONS_OVERRIDES_TABLE_V3(),
        engine=SHARDED_RAW_SESSION_OVERRIDES_DATA_TABLE_ENGINE_V3(),
    )


def RAW_SESSION_OVERRIDES_TABLE_MV_SQL_V3(where="TRUE"):
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


def SESSION_OVERRIDES_SNAPSHOT_TABLE_V3_CREATE_SQL(table_name: str) -> str:
    # these are the same field as the MV above, but with simpler types instead of aggregate function state
    engine = ReplacingMergeTree(
        table=table_name,
        replication_scheme=ReplicationScheme.REPLICATED,
        ver="max_inserted_at",
    )
    return f"""
CREATE TABLE IF NOT EXISTS {table_name} (
    team_id Int64,
    session_id_v7 UInt128,

    min_timestamp DateTime64(6, 'UTC'),
    max_timestamp DateTime64(6, 'UTC'),
    pageview_prio_timestamp_min DateTime64(6, 'UTC'),
    pageview_prio_timestamp_max DateTime64(6, 'UTC'),
    max_inserted_at DateTime64(6, 'UTC'),

    -- urls
    has_pageview_or_screen Boolean,
    entry_url Nullable(String),
    end_url Nullable(String),
    last_external_click_url Nullable(String),

    -- attribution
    entry_referring_domain Nullable(String),
    entry_utm_source Nullable(String),
    entry_utm_campaign Nullable(String),
    entry_utm_medium Nullable(String),
    entry_utm_term Nullable(String),
    entry_utm_content Nullable(String),
    entry_gclid Nullable(String),
    entry_gad_source Nullable(String),
    entry_fbclid Nullable(String),

    -- for channel type calculation, it's enough to know if these were present
    entry_has_gclid Boolean,
    entry_has_fbclid Boolean,

    -- for lower-tier ad ids, just put them in a map, and set of the ones present
    entry_ad_ids_map_keys Array(String),
    entry_ad_ids_map_values Array(String),
    entry_ad_ids_set Array(String),

    -- bounce rate
    page_screen_autocapture_uniq_up_to Array(UUID)
)
ENGINE = {engine}
ORDER BY (team_id, session_id_v7)
    """


def SESSION_OVERRIDES_SNAPSHOT_TABLE_V3_POPULATE_SQL(
    table_name: str, limit_clause: str = "", where_clause: str = "TRUE"
) -> str:
    return f"""
INSERT INTO {settings.CLICKHOUSE_DATABASE}.{table_name} (
    team_id,
    session_id_v7,

    min_timestamp,
    max_timestamp,
    pageview_prio_timestamp_min,
    pageview_prio_timestamp_max,

    max_inserted_at,
    has_pageview_or_screen,
    entry_url,
    end_url,
    last_external_click_url,

    entry_referring_domain,
    entry_utm_source,
    entry_utm_campaign,
    entry_utm_medium,
    entry_utm_term,
    entry_utm_content,
    entry_gclid,
    entry_gad_source,
    entry_fbclid,

    entry_has_gclid,
    entry_has_fbclid,

    entry_ad_ids_map_keys,
    entry_ad_ids_map_values,
    entry_ad_ids_set,

    page_screen_autocapture_uniq_up_to,
)
SELECT
    team_id,
    session_id_v7,

    min(s.min_timestamp) as min_timestamp,
    max(s.max_timestamp) as max_timestamp,
    max(s.max_inserted_at) as max_inserted_at,
    min(s.pageview_prio_timestamp_min) as pageview_prio_timestamp_min,
    max(s.pageview_prio_timestamp_max) as pageview_prio_timestamp_max,

    max(s.has_pageview_or_screen) as has_pageview_or_screen,
    argMinMerge(s.entry_url) as entry_url,
    argMaxMerge(s.end_url) as end_url,
    argMaxMerge(s.last_external_click_url) as last_external_click_url,

    argMinMerge(s.entry_utm_source) as entry_utm_source,
    argMinMerge(s.entry_utm_campaign) as entry_utm_campaign,
    argMinMerge(s.entry_utm_medium) as entry_utm_medium,
    argMinMerge(s.entry_utm_term) as entry_utm_term,
    argMinMerge(s.entry_utm_content) as entry_utm_content,
    argMinMerge(s.entry_referring_domain) as entry_referring_domain,
    argMinMerge(s.entry_gclid) as entry_gclid,
    argMinMerge(s.entry_gad_source) as entry_gad_source,
    argMinMerge(s.entry_fbclid) as entry_fbclid,

    argMinMerge(s.entry_has_gclid) as entry_has_gclid,
    argMinMerge(s.entry_has_fbclid) as entry_has_fbclid,

    mapKeys(argMinMerge(entry_ad_ids_map)) as entry_ad_ids_map_keys,
    mapValues(argMinMerge(entry_ad_ids_map)) as entry_ad_ids_map_values,
    argMinMerge(entry_ad_ids_set) as entry_ad_ids_set,

    groupUniqArrayMerge(2)(page_screen_autocapture_uniq_up_to) as page_screen_autocapture_uniq_up_to
FROM {settings.CLICKHOUSE_DATABASE}.{SHARDED_RAW_SESSIONS_OVERRIDES_TABLE_V3()} as s
WHERE s.max_inserted_at < %(timestamp)s
AND {where_clause}
GROUP BY team_id, session_id_v7
{limit_clause}
"""


def SESSIONS_OVERRIDES_DICT_V3_CREATE_SQL(
    dict_name: str, shards: int, max_execution_time: int, max_memory_usage: int
) -> str:
    return f"""
CREATE DICTIONARY IF NOT EXISTS {settings.CLICKHOUSE_DATABASE}.{dict_name} (
    team_id Int64,
    session_id_v7 UInt128,

    min_timestamp DateTime64(6, 'UTC'),
    max_timestamp DateTime64(6, 'UTC'),
    pageview_prio_timestamp_min DateTime64(6, 'UTC'),
    pageview_prio_timestamp_max DateTime64(6, 'UTC'),
    max_inserted_at DateTime64(6, 'UTC'),

    -- urls
    has_pageview_or_screen Boolean,
    entry_url Nullable(String),
    end_url Nullable(String),
    last_external_click_url Nullable(String),

    -- attribution
    entry_referring_domain Nullable(String),
    entry_utm_source Nullable(String),
    entry_utm_campaign Nullable(String),
    entry_utm_medium Nullable(String),
    entry_utm_term Nullable(String),
    entry_utm_content Nullable(String),
    entry_gclid Nullable(String),
    entry_gad_source Nullable(String),
    entry_fbclid Nullable(String),

    -- for channel type calculation, it's enough to know if these were present
    entry_has_gclid Boolean,
    entry_has_fbclid Boolean,

    -- for lower-tier ad ids, just put them in a map, and set of the ones present
    entry_ad_ids_map_keys Array(String),
    entry_ad_ids_map_values Array(String),
    entry_ad_ids_set Array(String),

    -- bounce rate
    page_screen_autocapture_uniq_up_to Array(UUID)
)
PRIMARY KEY team_id, session_id_v7
SOURCE(CLICKHOUSE(DB {settings.CLICKHOUSE_DATABASE} TABLE %(table)s USER %(user)s PASSWORD %(password)s))
LAYOUT(COMPLEX_KEY_HASHED(SHARDS {shards}))
LIFETIME(0)
SETTINGS(max_execution_time={max_execution_time}, max_memory_usage={max_memory_usage})
"""


def SESSION_OVERRIDES_SNAPSHOT_UPDATE_SQL(where="TRUE") -> str:
    return f"""
ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{EVENTS_DATA_TABLE()}
UPDATE
-- Timestamps - using min/max operations
    soe_min_timestamp = ifNull(
        least(
            soe_min_timestamp,
            dictGet(%(dict_name)s, 'min_timestamp', (team_id, `$session_id_uuid`))
        ),
        dictGet(%(dict_name)s, 'min_timestamp', (team_id, `$session_id_uuid`))
    ),

    soe_max_timestamp = ifNull(
        greatest(
            soe_max_timestamp,
            dictGet(%(dict_name)s, 'max_timestamp', (team_id, `$session_id_uuid`))
        ),
        dictGet(%(dict_name)s, 'max_timestamp', (team_id, `$session_id_uuid`))
    ),

    soe_pageview_prio_timestamp_min = ifNull(
        least(
            soe_pageview_prio_timestamp_min,
            dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`))
        ),
        dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`))
    ),

    soe_pageview_prio_timestamp_max = ifNull(
        greatest(
            soe_pageview_prio_timestamp_max,
            dictGet(%(dict_name)s, 'pageview_prio_timestamp_max', (team_id, `$session_id_uuid`))
        ),
        dictGet(%(dict_name)s, 'pageview_prio_timestamp_max', (team_id, `$session_id_uuid`))
    ),

    -- URLs - conditional based on timestamps
    soe_entry_url = if(
        soe_pageview_prio_timestamp_min < dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`)),
        soe_entry_url,
        dictGet(%(dict_name)s, 'entry_url', (team_id, `$session_id_uuid`))
    ),

    soe_end_url = if(
        soe_pageview_prio_timestamp_max > dictGet(%(dict_name)s, 'pageview_prio_timestamp_max', (team_id, `$session_id_uuid`)),
        soe_end_url,
        dictGet(%(dict_name)s, 'end_url', (team_id, `$session_id_uuid`))
    ),

    soe_last_external_click_url = if(
        soe_max_timestamp > dictGet(%(dict_name)s, 'max_timestamp', (team_id, `$session_id_uuid`)),
        soe_last_external_click_url,
        dictGet(%(dict_name)s, 'last_external_click_url', (team_id, `$session_id_uuid`))
    ),

    -- Attribution fields - all conditional on pageview_prio_timestamp_min
    soe_entry_referring_domain = if(
        soe_pageview_prio_timestamp_min < dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`)),
        soe_entry_referring_domain,
        dictGet(%(dict_name)s, 'entry_referring_domain', (team_id, `$session_id_uuid`))
    ),

    soe_entry_utm_source = if(
        soe_pageview_prio_timestamp_min < dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`)),
        soe_entry_utm_source,
        dictGet(%(dict_name)s, 'entry_utm_source', (team_id, `$session_id_uuid`))
    ),

    soe_entry_utm_campaign = if(
        soe_pageview_prio_timestamp_min < dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`)),
        soe_entry_utm_campaign,
        dictGet(%(dict_name)s, 'entry_utm_campaign', (team_id, `$session_id_uuid`))
    ),

    soe_entry_utm_medium = if(
        soe_pageview_prio_timestamp_min < dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`)),
        soe_entry_utm_medium,
        dictGet(%(dict_name)s, 'entry_utm_medium', (team_id, `$session_id_uuid`))
    ),

    soe_entry_utm_term = if(
        soe_pageview_prio_timestamp_min < dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`)),
        soe_entry_utm_term,
        dictGet(%(dict_name)s, 'entry_utm_term', (team_id, `$session_id_uuid`))
    ),

    soe_entry_utm_content = if(
        soe_pageview_prio_timestamp_min < dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`)),
        soe_entry_utm_content,
        dictGet(%(dict_name)s, 'entry_utm_content', (team_id, `$session_id_uuid`))
    ),

    soe_entry_gclid = if(
        soe_pageview_prio_timestamp_min < dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`)),
        soe_entry_gclid,
        dictGet(%(dict_name)s, 'entry_gclid', (team_id, `$session_id_uuid`))
    ),

    soe_entry_gad_source = if(
        soe_pageview_prio_timestamp_min < dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`)),
        soe_entry_gad_source,
        dictGet(%(dict_name)s, 'entry_gad_source', (team_id, `$session_id_uuid`))
    ),

    soe_entry_fbclid = if(
        soe_pageview_prio_timestamp_min < dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`)),
        soe_entry_fbclid,
        dictGet(%(dict_name)s, 'entry_fbclid', (team_id, `$session_id_uuid`))
    ),

    -- Boolean flags for channel type calculation
    soe_entry_has_gclid = if(
        soe_pageview_prio_timestamp_min < dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`)),
        soe_entry_has_gclid,
        dictGet(%(dict_name)s, 'entry_has_gclid', (team_id, `$session_id_uuid`))
    ),

    soe_entry_has_fbclid = if(
        soe_pageview_prio_timestamp_min < dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`)),
        soe_entry_has_fbclid,
        dictGet(%(dict_name)s, 'entry_has_fbclid', (team_id, `$session_id_uuid`))
    ),

    -- Maps and arrays for ad IDs
    soe_entry_ad_ids_map = if(
        soe_pageview_prio_timestamp_min < dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`)),
        soe_entry_ad_ids_map,
        mapFromArrays(
            dictGet(%(dict_name)s, 'entry_ad_ids_map_keys', (team_id, `$session_id_uuid`)),
            dictGet(%(dict_name)s, 'entry_ad_ids_map_values', (team_id, `$session_id_uuid`))
        )
    ),

    soe_entry_ad_ids_set = if(
        soe_pageview_prio_timestamp_min < dictGet(%(dict_name)s, 'pageview_prio_timestamp_min', (team_id, `$session_id_uuid`)),
        soe_entry_ad_ids_set,
        dictGet(%(dict_name)s, 'entry_ad_ids_set', (team_id, `$session_id_uuid`))
    ),

    -- Bounce rate - merge arrays, keeping max 2 unique elements
    soe_page_screen_autocapture_uniq_up_to = arrayResize(
        arrayDistinct(
            arrayConcat(
                ifNull(soe_page_screen_autocapture_uniq_up_to, []),
                dictGet(%(dict_name)s, 'page_screen_autocapture_uniq_up_to', (team_id, `$session_id_uuid`))
            )
        ),
        2
    )
   WHERE dictHas(%(dict_name)s, (team_id, `$session_id_uuid`)) AND {where}
"""


RAW_SESSION_OVERRIDES_VIEW_NAME_V3 = f"{TABLE_BASE_NAME_V3}_v"

# this view isn't used in production, but it's very useful for testing, and there's almost no overhead to keeping it around
RAW_SESSION_OVERRIDES_CREATE_OR_REPLACE_VIEW_SQL_V3 = (
    lambda: f"""
CREATE OR REPLACE VIEW {RAW_SESSION_OVERRIDES_VIEW_NAME_V3} AS
SELECT
    session_id_v7,
    session_timestamp,
    team_id,

    min(min_timestamp) as min_timestamp,
    max(max_timestamp) as max_timestamp,
    max(max_inserted_at) as max_inserted_at,
    min(pageview_prio_timestamp_min) as pageview_prio_timestamp_min,
    max(pageview_prio_timestamp_max) as pageview_prio_timestamp_max,

    -- urls
    max(has_pageview_or_screen) as has_pageview_or_screen,
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

    -- bounce rate
    groupUniqArrayMerge(2)(page_screen_autocapture_uniq_up_to) as page_screen_autocapture_uniq_up_to
FROM {settings.CLICKHOUSE_DATABASE}.{DISTRIBUTED_RAW_SESSIONS_OVERRIDES_TABLE_V3()}
GROUP BY session_id_v7, session_timestamp, team_id
"""
)

RAW_SESSION_OVERRIDES_EVENTS_VIEW_NAME_V3 = f"{TABLE_BASE_NAME_V3}_events_v"


# this view also isn't used in production
# use it in testing to make sure that the events table joined with the overrides table gives the correct results
RAW_SESSION_OVERRIDES_CREATE_OR_REPLACE_EVENTS_VIEW_SQL_V3 = (
    lambda: f"""
CREATE OR REPLACE VIEW {RAW_SESSION_OVERRIDES_EVENTS_VIEW_NAME_V3} AS
SELECT
    $session_id_uuid,
    session_id_v7,
    team_id,
    ifNull(
        least(
            e.soe_min_timestamp,
            s.min_timestamp
        ),
        s.min_timestamp
    ) as soe_min_timestamp,
    ifNull(
        greatest(
            e.soe_max_timestamp,
            s.max_timestamp
        ),
        s.max_timestamp
    ) as soe_max_timestamp,
    ifNull(
        least(
            e.soe_pageview_prio_timestamp_min,
            s.pageview_prio_timestamp_min
        ),
        s.pageview_prio_timestamp_min
    ) as soe_pageview_prio_timestamp_min,
    ifNull(
        greatest(
            e.soe_pageview_prio_timestamp_max,
            s.pageview_prio_timestamp_max
        ),
        s.pageview_prio_timestamp_max
    ) as soe_pageview_prio_timestamp_max,

    -- urls
    if(
        e.soe_pageview_prio_timestamp_min < s.pageview_prio_timestamp_min,
        e.soe_entry_url,
        s.entry_url
    ) as soe_entry_url

FROM
    events as e
LEFT JOIN (
    SELECT
        session_id_v7,
        session_timestamp,
        team_id,

        min(min_timestamp) as min_timestamp,
        max(max_timestamp) as max_timestamp,
        max(max_inserted_at) as max_inserted_at,
        min(pageview_prio_timestamp_min) as pageview_prio_timestamp_min,
        max(pageview_prio_timestamp_max) as pageview_prio_timestamp_max,

        -- urls
        max(has_pageview_or_screen) as has_pageview_or_screen,
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

        -- bounce rate
        groupUniqArrayMerge(2)(page_screen_autocapture_uniq_up_to) as page_screen_autocapture_uniq_up_to
    FROM {settings.CLICKHOUSE_DATABASE}.{DISTRIBUTED_RAW_SESSIONS_OVERRIDES_TABLE_V3()}
    GROUP BY session_id_v7, session_timestamp, team_id
    ) as s
ON e.`$session_id_uuid` = s.session_id_v7 AND e.team_id = s.team_id
"""
)

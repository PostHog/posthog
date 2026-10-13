from typing import Optional

from django.conf import settings

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


# Re-exported from the Django-free posthog.raw_sessions_v3_ad_ids module so the HogQL schema can
# use it without booting Django; kept importable here for existing callers.
from posthog.raw_sessions_v3_ad_ids import SESSION_V3_LOWER_TIER_AD_IDS  # noqa: E402

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
            `$host` Nullable(String),
{f",{new_line}".join([f"            `{ad_id}` Nullable(String)" for ad_id in SESSION_V3_LOWER_TIER_AD_IDS])}
        )') as p,
        JSONExtractString(person_properties, 'email') as _person_email,
        tupleElement(p, '$current_url') as _current_url,
        tupleElement(p, '$external_click_url') as _external_click_url,
        tupleElement(p, '$browser') as _browser,
        tupleElement(p, '$browser_version') as _browser_version,
        tupleElement(p, '$os') as _os,
        tupleElement(p, '$os_version') as _os_version,
        tupleElement(p, '$device_type') as _device_type,
        tupleElement(p, '$viewport_width') as _viewport_width,
        tupleElement(p, '$viewport_height') as _viewport_height,
        tupleElement(p, '$geoip_country_code') as _geoip_country_code,
        tupleElement(p, '$geoip_subdivision_1_code') as _geoip_subdivision_1_code,
        tupleElement(p, '$geoip_subdivision_1_name') as _geoip_subdivision_1_name,
        tupleElement(p, '$geoip_subdivision_city_name') as _geoip_subdivision_city_name,
        tupleElement(p, '$geoip_time_zone') as _geoip_time_zone,
        tupleElement(p, '$referring_domain') as _referring_domain,
        tupleElement(p, 'utm_source') as _utm_source,
        tupleElement(p, 'utm_campaign') as _utm_campaign,
        tupleElement(p, 'utm_medium') as _utm_medium,
        tupleElement(p, 'utm_term') as _utm_term,
        tupleElement(p, 'utm_content') as _utm_content,
        tupleElement(p, 'gclid') as _gclid,
        tupleElement(p, 'gad_source') as _gad_source,
        tupleElement(p, 'fbclid') as _fbclid,
{f",{new_line}".join([f"        tupleElement(p, '{ad_id}') as {ad_id}" for ad_id in SESSION_V3_LOWER_TIER_AD_IDS])},
        CAST(mapFilter((k, v) -> v IS NOT NULL, map(
{f",{new_line}".join([f"            '{ad_id}', {ad_id}" for ad_id in SESSION_V3_LOWER_TIER_AD_IDS])}
        )) AS Map(String, String)) as ad_ids_map,
        CAST(arrayFilter(x -> x IS NOT NULL, [
{f",{new_line}".join([f"            if({ad_id} IS NOT NULL, '{ad_id}', NULL)" for ad_id in SESSION_V3_LOWER_TIER_AD_IDS])}
        ]) AS Array(String)) as ad_ids_set,
        tupleElement(p, '$host') as _host"""


def RAW_SESSION_TABLE_MV_SELECT_SQL_V3(source_table, where="TRUE", include_session_timestamp=False, extra_ctes=""):
    return """
WITH
    {extra_ctes}{PROPERTIES},
    -- attribution properties from non-pageview/screen events should be deprioritized, so make the timestamp +/- 1 year so they sort last
    if (event = '$pageview' OR event = '$screen', timestamp, timestamp + toIntervalYear(1)) as pageview_prio_timestamp_min,
    if (event = '$pageview' OR event = '$screen', timestamp, timestamp - toIntervalYear(1)) as pageview_prio_timestamp_max
SELECT
    team_id,
    `$session_id_uuid` AS session_id_v7,
    {session_timestamp}

    initializeAggregation('argMaxState', source_table.distinct_id, timestamp) as distinct_id,
    initializeAggregation('groupUniqArrayState', source_table.distinct_id) as distinct_ids,

    timestamp AS min_timestamp,
    timestamp AS max_timestamp,
    inserted_at AS max_inserted_at,

    -- urls - only update if the event is a pageview or screen
    if(_current_url IS NOT NULL AND (event = '$pageview' OR event = '$screen'), [_current_url], []) AS urls,
    initializeAggregation('argMinState', _current_url, pageview_prio_timestamp_min) as entry_url,
    initializeAggregation('argMaxState', _current_url, pageview_prio_timestamp_max) as end_url,
    initializeAggregation('argMaxState', _external_click_url, timestamp) as last_external_click_url,

    -- device
    initializeAggregation('argMinState', _browser, timestamp) as browser,
    initializeAggregation('argMinState', _browser_version, timestamp) as browser_version,
    initializeAggregation('argMinState', _os, timestamp) as os,
    initializeAggregation('argMinState', _os_version, timestamp) as os_version,
    initializeAggregation('argMinState', _device_type, timestamp) as device_type,
    initializeAggregation('argMinState', _viewport_width, timestamp) as viewport_width,
    initializeAggregation('argMinState', _viewport_height, timestamp) as viewport_height,

    -- geo ip
    initializeAggregation('argMinState', _geoip_country_code, timestamp) as geoip_country_code,
    initializeAggregation('argMinState', _geoip_subdivision_1_code, timestamp) as geoip_subdivision_1_code,
    initializeAggregation('argMinState', _geoip_subdivision_1_name, timestamp) as geoip_subdivision_1_name,
    initializeAggregation('argMinState', _geoip_subdivision_city_name, timestamp) as geoip_subdivision_city_name,
    initializeAggregation('argMinState', _geoip_time_zone, timestamp) as geoip_time_zone,

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

    -- channel type
    initializeAggregation('argMinState', tuple(_utm_source, _utm_medium, _utm_campaign, _referring_domain, _gclid IS NOT NULL, _fbclid IS NOT NULL, _gad_source), pageview_prio_timestamp_min) as entry_channel_type_properties,


    -- counts
    initializeAggregation('uniqExactState', if(event='$pageview', uuid, NULL)) as pageview_uniq,
    initializeAggregation('uniqExactState', if(event='$autocapture', uuid, NULL)) as autocapture_uniq,
    initializeAggregation('uniqExactState', if(event='$screen', uuid, NULL)) as screen_uniq,

    -- perf
    initializeAggregation('uniqUpToState(1)', if(event='$pageview' OR event='$screen', uuid, NULL)) as page_screen_uniq_up_to,
    event = '$autocapture' as has_autocapture,

    -- flags
    arrayMap((k, v) -> concat(k, '=', v), mapKeys(properties_group_feature_flags), mapValues(properties_group_feature_flags)) as flag_key_values,
    mapKeys(properties_group_feature_flags) as flag_keys,

    -- event names
    [event] as event_names,

    -- hosts
    if(_host IS NOT NULL AND _host != '', [_host], []) AS hosts,

    -- emails
    if(_person_email IS NOT NULL AND _person_email != '', [_person_email], []) AS emails,

    false as has_replay_events
FROM {source_table} AS source_table
WHERE bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(`$session_id`, 'UUID')), 76), 0xF) == 7 -- has a session id and is valid uuidv7
AND {where}
    """.format(
        source_table=source_table,
        where=where,
        PROPERTIES=PROPERTIES,
        extra_ctes=extra_ctes,
        session_timestamp="fromUnixTimestamp64Milli(toUInt64(bitShiftRight(`$session_id_uuid`, 80))) AS session_timestamp,"
        if include_session_timestamp
        else "",
    )


# WarpStream ingestion pipeline on the ingestion-events cluster: Kafka table -> MV -> writable.
# The ws2 names stay clear of the earlier hand-managed pipeline's objects, which hold the
# unsuffixed names outside repo control.


def RAW_SESSION_TABLE_MV_RECORDINGS_SELECT_SQL_V3(source_table, where="TRUE", include_session_timestamp=False):
    return """
WITH
    min_first_timestamp as timestamp,
    CAST(fromUnixTimestamp64Milli(9223372036854775), 'DateTime64(6)') as max_ts_64, -- max positive Int64 / 1000
    CAST(fromUnixTimestamp64Milli(-9223372036854775), 'DateTime64(6)') as min_ts_64, -- max negative Int64 / 1000
    CAST(NULL, 'Nullable(String)') as null_s,
    CAST(NULL, 'Nullable(Int64)') as null_i64,
    CAST(NULL, 'Nullable(UUID)') as null_uuid
SELECT
    team_id,
    toUInt128(accurateCast(session_id, 'UUID')) AS session_id_v7,
    {session_timestamp}
    initializeAggregation('argMaxState', source_table.distinct_id, min_ts_64) as distinct_id,
    initializeAggregation('groupUniqArrayState', source_table.distinct_id) as distinct_ids,

    timestamp AS min_timestamp,
    timestamp AS max_timestamp,
    fromUnixTimestamp(0) AS max_inserted_at,

    -- urls - only update if the event is a pageview or screen
    CAST([], 'Array(String)') AS urls,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_url,
    initializeAggregation('argMaxState', null_s, min_ts_64) as end_url,
    initializeAggregation('argMaxState', null_s, min_ts_64) as last_external_click_url,

    -- device
    initializeAggregation('argMinState', null_s, max_ts_64) as browser,
    initializeAggregation('argMinState', null_s, max_ts_64) as browser_version,
    initializeAggregation('argMinState', null_s, max_ts_64) as os,
    initializeAggregation('argMinState', null_s, max_ts_64) as os_version,
    initializeAggregation('argMinState', null_s, max_ts_64) as device_type,
    initializeAggregation('argMinState', null_i64, max_ts_64) as viewport_width,
    initializeAggregation('argMinState', null_i64, max_ts_64) as viewport_height,

    -- geo ip
    initializeAggregation('argMinState', null_s, max_ts_64) as geoip_country_code,
    initializeAggregation('argMinState', null_s, max_ts_64) as geoip_subdivision_1_code,
    initializeAggregation('argMinState', null_s, max_ts_64) as geoip_subdivision_1_name,
    initializeAggregation('argMinState', null_s, max_ts_64) as geoip_subdivision_city_name,
    initializeAggregation('argMinState', null_s, max_ts_64) as geoip_time_zone,

    -- attribution
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_referring_domain,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_utm_source,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_utm_campaign,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_utm_medium,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_utm_term,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_utm_content,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_gclid,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_gad_source,
    initializeAggregation('argMinState', null_s, max_ts_64) as entry_fbclid,

    -- has gclid/fbclid for reading fewer bytes when calculating channel type
    initializeAggregation('argMinState', false, max_ts_64) as entry_has_gclid,
    initializeAggregation('argMinState', false, max_ts_64) as entry_has_fbclid,

    -- other ad ids
    initializeAggregation('argMinState', CAST(map(), 'Map(String, String)'), max_ts_64) as entry_ad_ids_map,
    initializeAggregation('argMinState', CAST([], 'Array(String)'), max_ts_64) as entry_ad_ids_set,

    -- channel type
    initializeAggregation('argMinState', tuple(null_s, null_s, null_s, null_s, false, false, null_s), max_ts_64) as entry_channel_type_properties,

    -- counts
    initializeAggregation('uniqExactState', null_uuid) as pageview_uniq,
    initializeAggregation('uniqExactState', null_uuid) as autocapture_uniq,
    initializeAggregation('uniqExactState', null_uuid) as screen_uniq,

    -- perf
    initializeAggregation('uniqUpToState(1)', null_uuid) as page_screen_uniq_up_to,
    false as has_autocapture,

    -- flags
    CAST([], 'Array(String)') as flag_key_values,
    CAST([], 'Array(String)') as flag_keys,

    -- event names
    CAST([], 'Array(String)') as event_names,

    -- hosts
    CAST([], 'Array(String)') as hosts,

    -- emails
    CAST([], 'Array(String)') as emails,

    -- replay
    true as has_replay_events
FROM {source_table} AS source_table
WHERE bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(session_id, 'UUID')), 76), 0xF) == 7 -- has a session id and is valid uuidv7
AND {where}
    """.format(
        source_table=source_table,
        where=where,
        session_timestamp="fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80))) AS session_timestamp,"
        if include_session_timestamp
        else "",
    )


def RAW_SESSION_TABLE_BACKFILL_SQL_V3(
    where: str,
    shard_index: Optional[int] = None,
    num_shards: Optional[int] = None,
    target_table: Optional[str] = None,
    include_session_timestamp: bool = True,
):
    """
    Generates SQL to backfill sessions from events.

    Each shard should call this with its own shard_index to only SELECT events
    that will end up on that shard, then INSERT directly to the local sharded table.

    include_session_timestamp must be True when the target table has session_timestamp
    as DEFAULT (sharded/writable tables), and False when it is MATERIALIZED (distributed).
    """
    if not target_table:
        target_table = SHARDED_RAW_SESSIONS_TABLE_V3()
    if shard_index is not None and num_shards is not None:
        shard_filter = f"modulo(cityHash64(`$session_id_uuid`), {num_shards}) = {shard_index}"
        combined_where = f"({where}) AND {shard_filter}"
    else:
        combined_where = where

    return """
INSERT INTO {database}.{target_table}
{select_sql}
""".format(
        database=settings.CLICKHOUSE_DATABASE,
        target_table=target_table,
        select_sql=RAW_SESSION_TABLE_MV_SELECT_SQL_V3(
            where=combined_where,
            source_table=f"{settings.CLICKHOUSE_DATABASE}.events",
            include_session_timestamp=include_session_timestamp,
        ),
    )


def RAW_SESSION_TABLE_BACKFILL_RECORDINGS_SQL_V3(
    where: str,
    shard_index: Optional[int] = None,
    num_shards: Optional[int] = None,
    target_table: Optional[str] = None,
    include_session_timestamp: bool = True,
):
    """
    Generates SQL to backfill sessions from session replay events.

    Each shard should call this with its own shard_index to only SELECT recordings
    that will end up on that shard, then INSERT directly to the local sharded table.

    include_session_timestamp must be True when the target table has session_timestamp
    as DEFAULT (sharded/writable tables), and False when it is MATERIALIZED (distributed).
    """
    if not target_table:
        target_table = SHARDED_RAW_SESSIONS_TABLE_V3()
    if shard_index is not None and num_shards is not None:
        shard_filter = f"modulo(cityHash64(toUInt128(accurateCast(session_id, 'UUID'))), {num_shards}) = {shard_index}"
        combined_where = f"({where}) AND {shard_filter}"
    else:
        combined_where = where

    return """
INSERT INTO {database}.{target_table}
{select_sql}
""".format(
        database=settings.CLICKHOUSE_DATABASE,
        target_table=target_table,
        select_sql=RAW_SESSION_TABLE_MV_RECORDINGS_SELECT_SQL_V3(
            where=combined_where,
            source_table=f"{settings.CLICKHOUSE_DATABASE}.session_replay_events",
            include_session_timestamp=include_session_timestamp,
        ),
    )


# Distributed engine tables are only created if CLICKHOUSE_REPLICATED

# This table is responsible for writing to sharded_sessions based on a sharding key.


# This table is responsible for reading from sessions on a cluster setting


def GET_NUM_RAW_SESSIONS_ACTIVE_PARTS(
    partitions: list[str],
    *,
    table: str | None = None,
    use_cluster: bool = True,
) -> str:
    """Get the maximum number of active parts across specified partitions.

    ClickHouse's parts_to_throw_insert is per-partition, so this checks the max
    active parts in any single (host, partition) combination.

    Args:
        partitions: List of partition names in YYYYMM format (e.g., ['202501', '202412'])
        table: Table name to check. Defaults to the sharded raw sessions table.
        use_cluster: If True, query across all cluster replicas. If False, query
            only the local node's system.parts (useful for standalone/experimental nodes).
    """
    if not partitions:
        raise ValueError("partitions list cannot be empty")
    # Format partitions for SQL IN clause: ('202501', '202412')
    partitions_sql = ", ".join(f"'{p}'" for p in partitions)
    table = table or SHARDED_RAW_SESSIONS_TABLE_V3()
    parts_table = (
        f"clusterAllReplicas('{settings.CLICKHOUSE_CLUSTER}', system.parts)" if use_cluster else "system.parts"
    )

    return f"""
        SELECT coalesce(max(parts_count), 0), argMax(partition, parts_count), argMax(host, parts_count)
        FROM (
            SELECT hostName() as host, count() as parts_count, partition
            FROM {parts_table}
            WHERE database = currentDatabase()
              AND table = '{table}'
              AND partition IN ({partitions_sql})
              AND active = 1
            GROUP BY host, partition
        )
    """

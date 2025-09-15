from django.conf import settings

from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

TABLE_BASE_NAME = "raw_sessions"


def SHARDED_RAW_SESSIONS_DATA_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def WRITABLE_RAW_SESSIONS_DATA_TABLE():
    return f"writable_{TABLE_BASE_NAME}"


def TRUNCATE_RAW_SESSIONS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_RAW_SESSIONS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"


def DROP_RAW_SESSION_SHARDED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_RAW_SESSIONS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"


def DROP_RAW_SESSION_DISTRIBUTED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {TABLE_BASE_NAME} {ON_CLUSTER_CLAUSE()}"


def DROP_RAW_SESSION_WRITABLE_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {WRITABLE_RAW_SESSIONS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"


def DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL():
    return f"DROP TABLE IF EXISTS {TABLE_BASE_NAME}_mv {ON_CLUSTER_CLAUSE()}"


def DROP_RAW_SESSION_VIEW_SQL():
    return f"DROP VIEW IF EXISTS {TABLE_BASE_NAME}_v {ON_CLUSTER_CLAUSE()}"


# if updating these column definitions
# you'll need to update the explicit column definitions in the materialized view creation statement below
RAW_SESSIONS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    team_id Int64,
    session_id_v7 UInt128, -- integer representation of a uuidv7

    -- ClickHouse will pick the latest value of distinct_id for the session
    -- this is fine since even if the distinct_id changes during a session
    distinct_id AggregateFunction(argMax, String, DateTime64(6, 'UTC')),

    min_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    max_inserted_at SimpleAggregateFunction(max, DateTime64(6, 'UTC')),

    -- urls
    urls SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    entry_url AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    end_url AggregateFunction(argMax, String, DateTime64(6, 'UTC')),
    last_external_click_url AggregateFunction(argMax, String, DateTime64(6, 'UTC')),

    -- device
    initial_browser AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_browser_version AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_os AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_os_version AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_device_type AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_viewport_width AggregateFunction(argMin, Int64, DateTime64(6, 'UTC')),
    initial_viewport_height AggregateFunction(argMin, Int64, DateTime64(6, 'UTC')),

    -- geoip
    -- only store the properties we actually use, as there's tons, see https://posthog.com/docs/cdp/geoip-enrichment
    initial_geoip_country_code AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_geoip_subdivision_1_code AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_geoip_subdivision_1_name AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_geoip_subdivision_city_name AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_geoip_time_zone AggregateFunction(argMin, String, DateTime64(6, 'UTC')),

    -- attribution
    initial_referring_domain AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_source AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_campaign AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_medium AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_term AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_utm_content AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_gclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_gad_source AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_gclsrc AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_dclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_gbraid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_wbraid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_fbclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_msclkid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_twclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_li_fat_id AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_mc_cid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_igshid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_ttclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_epik AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_qclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_sccid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial__kx AggregateFunction(argMin, String, DateTime64(6, 'UTC')),
    initial_irclid AggregateFunction(argMin, String, DateTime64(6, 'UTC')),

    -- Count pageview, autocapture, and screen events for providing totals.
    -- It's unclear if we can use the counts as they are not idempotent, and we had a bug on EU where events were
    -- double-counted, so the counts were wrong. To get around this, also keep track of the unique uuids. This will be
    -- slower and more expensive to store, but will be correct even if events are double-counted, so can be used to
    -- verify correctness and as a backup. Ideally we will be able to delete the uniq columns in the future when we're
    -- satisfied that counts are accurate.
    pageview_count SimpleAggregateFunction(sum, Int64),
    pageview_uniq AggregateFunction(uniq, Nullable(UUID)),
    autocapture_count SimpleAggregateFunction(sum, Int64),
    autocapture_uniq AggregateFunction(uniq, Nullable(UUID)),
    screen_count SimpleAggregateFunction(sum, Int64),
    screen_uniq AggregateFunction(uniq, Nullable(UUID)),

    -- replay
    maybe_has_session_replay SimpleAggregateFunction(max, Bool), -- will be written False to by the events table mv and True to by the replay table mv

    -- as a performance optimisation, also keep track of the uniq events for all of these combined, a bounce is a session with <2 of these
    page_screen_autocapture_uniq_up_to AggregateFunction(uniqUpTo(1), Nullable(UUID)),

    -- web vitals
    vitals_lcp AggregateFunction(argMin, Nullable(Float64), DateTime64(6, 'UTC'))
) ENGINE = {engine}
"""


def RAW_SESSIONS_DATA_TABLE_ENGINE():
    return AggregatingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED)


# The fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000)) part is just extracting the timestamp
# part of a UUID v7.
# This table is designed to be useful for both very fast recent lookups (e.g. "realtime" dashboards) but also for
# sampling over longer time periods. I chose toStartOfHour instead of toStartOfDay because it means that queries over
# very recent data (e.g. the last hour) would only need to scan up to 2 hours of data rather than up to 25 hours.
#
# I could have used a smaller interval like toStartOfMinute, but this would reduce the benefit of sampling, as the sampling
# would not allow use to skip entire granules (which are 8192 rows by default).
#
# E.g. if we wanted to sample only 1/Nth of our data, then to read only 1/nth of the data on disk we would want one
# interval to have GRANULE_SIZE * N rows.
# Example: For a customer with 1M sessions per day, an interval of 1 hour and a GRANULE_SIZE of 8192, we get a N of
# 1M / 24 / 8192 = ~5. So we could sample around 1/5th of the data and get around a 5x speedup (probably a bit less in
# practice). With the same customer, if we used an interval of 1 minute, we would get an N of
# 1M / 24 / 60 / 8192 = ~0.08. This is <1, so we wouldn't benefit much from sampling.


def RAW_SESSIONS_TABLE_SQL(on_cluster=True):
    return (
        RAW_SESSIONS_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMM(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000)))
ORDER BY (
    team_id,
    toStartOfHour(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000))),
    cityHash64(session_id_v7),
    session_id_v7
)
SAMPLE BY cityHash64(session_id_v7)
"""
    ).format(
        table_name=SHARDED_RAW_SESSIONS_DATA_TABLE(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=RAW_SESSIONS_DATA_TABLE_ENGINE(),
    )


def source_url_column(column_name: str) -> str:
    return f"nullIf(JSONExtractString(properties, '{column_name}'), '')"


def source_string_column(column_name: str) -> str:
    return f"JSONExtractString(properties, '{column_name}')"


def source_int_column(column_name: str) -> str:
    return f"JSONExtractInt(properties, '{column_name}')"


def source_nullable_float_column(column_name: str) -> str:
    # this is what we do in queries, but it seems pretty awful
    return f"""accurateCastOrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, '{column_name}'), ''), 'null'), '^"|"$', ''), 'Float64')"""


RAW_SESSION_TABLE_BACKFILL_SELECT_SQL = (
    lambda: """
SELECT
    team_id,
    toUInt128(toUUID(`$session_id`)) as session_id_v7,

    initializeAggregation('argMaxState', distinct_id, timestamp) as distinct_id,

    timestamp AS min_timestamp,
    timestamp AS max_timestamp,
    inserted_at AS max_inserted_at,

    -- urls
    if({current_url} IS NOT NULL, [{current_url}], []) AS urls,
    initializeAggregation('argMinState', {current_url_string}, timestamp) as entry_url,
    initializeAggregation('argMaxState', {current_url_string}, timestamp) as end_url,
    initializeAggregation('argMaxState', {external_click_url}, timestamp) as last_external_click_url,

    -- device
    initializeAggregation('argMinState', {browser}, timestamp) as browser,
    initializeAggregation('argMinState', {browser_version}, timestamp) as browser_version,
    initializeAggregation('argMinState', {os}, timestamp) as os,
    initializeAggregation('argMinState', {os_version}, timestamp) as os_version,
    initializeAggregation('argMinState', {device_type}, timestamp) as device_type,
    initializeAggregation('argMinState', {viewport_width}, timestamp) as viewport_width,
    initializeAggregation('argMinState', {viewport_height}, timestamp) as viewport_height,

    -- geo ip
    initializeAggregation('argMinState', {geoip_country_code}, timestamp) as initial_geoip_country_code,
    initializeAggregation('argMinState', {geoip_subdivision_1_code}, timestamp) as initial_geoip_subdivision_1_code,
    initializeAggregation('argMinState', {geoip_subdivision_1_name}, timestamp) as initial_geoip_subdivision_1_name,
    initializeAggregation('argMinState', {geoip_subdivision_city_name}, timestamp) as initial_geoip_subdivision_city_name,
    initializeAggregation('argMinState', {geoip_time_zone}, timestamp) as initial_geoip_time_zone,

    -- attribution
    initializeAggregation('argMinState', {referring_domain}, timestamp) as initial_referring_domain,
    initializeAggregation('argMinState', {utm_source}, timestamp) as initial_utm_source,
    initializeAggregation('argMinState', {utm_campaign}, timestamp) as initial_utm_campaign,
    initializeAggregation('argMinState', {utm_medium}, timestamp) as initial_utm_medium,
    initializeAggregation('argMinState', {utm_term}, timestamp) as initial_utm_term,
    initializeAggregation('argMinState', {utm_content}, timestamp) as initial_utm_content,
    initializeAggregation('argMinState', {gclid}, timestamp) as initial_gclid,
    initializeAggregation('argMinState', {gad_source}, timestamp) as initial_gad_source,
    initializeAggregation('argMinState', {gclsrc}, timestamp) as initial_gclsrc,
    initializeAggregation('argMinState', {dclid}, timestamp) as initial_dclid,
    initializeAggregation('argMinState', {gbraid}, timestamp) as initial_gbraid,
    initializeAggregation('argMinState', {wbraid}, timestamp) as initial_wbraid,
    initializeAggregation('argMinState', {fbclid}, timestamp) as initial_fbclid,
    initializeAggregation('argMinState', {msclkid}, timestamp) as initial_msclkid,
    initializeAggregation('argMinState', {twclid}, timestamp) as initial_twclid,
    initializeAggregation('argMinState', {li_fat_id}, timestamp) as initial_li_fat_id,
    initializeAggregation('argMinState', {mc_cid}, timestamp) as initial_mc_cid,
    initializeAggregation('argMinState', {igshid}, timestamp) as initial_igshid,
    initializeAggregation('argMinState', {ttclid}, timestamp) as initial_ttclid,
    initializeAggregation('argMinState', {epik}, timestamp) as initial_epik,
    initializeAggregation('argMinState', {qclid}, timestamp) as initial_qclid,
    initializeAggregation('argMinState', {sccid}, timestamp) as initial_sccid,
    initializeAggregation('argMinState', {kx}, timestamp) as initial__kx,
    initializeAggregation('argMinState', {irclid}, timestamp) as initial_irclid,

    -- counts
    if(event='$pageview', 1, 0) as pageview_count,
    initializeAggregation('uniqState', if(event='$pageview', uuid, NULL)) as pageview_uniq,
    if(event='$autocapture', 1, 0) as autocapture_count,
    initializeAggregation('uniqState', if(event='autocapture', uuid, NULL)) as autocapture_uniq,
    if(event='$screen', 1, 0) as screen_count,
    initializeAggregation('uniqState', if(event='screen', uuid, NULL)) as screen_uniq,

    -- replay
    false as maybe_has_session_replay,

    -- perf
    initializeAggregation('uniqUpToState(1)', if(event='$pageview' OR event='$screen' OR event='$autocapture', uuid, NULL)) as page_screen_autocapture_uniq_up_to,

    -- vitals
    initializeAggregation('argMinState', {vitals_lcp}, timestamp) as vitals_lcp
FROM {database}.events
WHERE bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(`$session_id`, 'UUID')), 76), 0xF) == 7 -- has a session id and is valid uuidv7
""".format(
        database=settings.CLICKHOUSE_DATABASE,
        current_url=source_url_column("$current_url"),
        current_url_string=source_string_column("$current_url"),
        external_click_url=source_string_column("$external_click_url"),
        browser=source_string_column("$browser"),
        browser_version=source_string_column("$browser_version"),
        os=source_string_column("$os"),
        os_version=source_string_column("$os_version"),
        device_type=source_string_column("$device_type"),
        viewport_width=source_int_column("$viewport_width"),
        viewport_height=source_int_column("$viewport_height"),
        geoip_country_code=source_string_column("$geoip_country_code"),
        geoip_subdivision_1_code=source_string_column("$geoip_subdivision_1_code"),
        geoip_subdivision_1_name=source_string_column("$geoip_subdivision_1_name"),
        geoip_subdivision_city_name=source_string_column("$geoip_subdivision_city_name"),
        geoip_time_zone=source_string_column("$geoip_time_zone"),
        referring_domain=source_string_column("$referring_domain"),
        utm_source=source_string_column("utm_source"),
        utm_campaign=source_string_column("utm_campaign"),
        utm_medium=source_string_column("utm_medium"),
        utm_term=source_string_column("utm_term"),
        utm_content=source_string_column("utm_content"),
        gclid=source_string_column("gclid"),
        gad_source=source_string_column("gad_source"),
        gclsrc=source_string_column("gclsrc"),
        dclid=source_string_column("dclid"),
        gbraid=source_string_column("gbraid"),
        wbraid=source_string_column("wbraid"),
        fbclid=source_string_column("fbclid"),
        msclkid=source_string_column("msclkid"),
        twclid=source_string_column("twclid"),
        li_fat_id=source_string_column("li_fat_id"),
        mc_cid=source_string_column("mc_cid"),
        igshid=source_string_column("igshid"),
        ttclid=source_string_column("ttclid"),
        epik=source_string_column("epik"),
        qclid=source_string_column("qclid"),
        sccid=source_string_column("sccid"),
        kx=source_string_column("_kx"),
        irclid=source_string_column("irclid"),
        vitals_lcp=source_nullable_float_column("$web_vitals_LCP_value"),
    )
)


RAW_SESSION_TABLE_MV_SELECT_SQL = (
    lambda: """
SELECT
    team_id,
    toUInt128(toUUID(`$session_id`)) as session_id_v7,

    argMaxState(distinct_id, timestamp) as distinct_id,

    min(timestamp) AS min_timestamp,
    max(timestamp) AS max_timestamp,
    max(coalesce(inserted_at, now64())) AS max_inserted_at, -- use coalesce to ensure we have a value even if the event is created with inserted_at=NULL

    -- urls
    groupUniqArray({current_url}) AS urls,
    argMinState({current_url_string}, timestamp) as entry_url,
    argMaxState({current_url_string}, timestamp) as end_url,
    argMaxState({external_click_url}, timestamp) as last_external_click_url,

    -- device
    argMinState({browser}, timestamp) as initial_browser,
    argMinState({browser_version}, timestamp) as initial_browser_version,
    argMinState({os}, timestamp) as initial_os,
    argMinState({os_version}, timestamp) as initial_os_version,
    argMinState({device_type}, timestamp) as initial_device_type,
    argMinState({viewport_width}, timestamp) as initial_viewport_width,
    argMinState({viewport_height}, timestamp) as initial_viewport_height,

    -- geoip
    argMinState({geoip_country_code}, timestamp) as initial_geoip_country_code,
    argMinState({geoip_subdivision_1_code}, timestamp) as initial_geoip_subdivision_1_code,
    argMinState({geoip_subdivision_1_name}, timestamp) as initial_geoip_subdivision_1_name,
    argMinState({geoip_subdivision_city_name}, timestamp) as initial_geoip_subdivision_city_name,
    argMinState({geoip_time_zone}, timestamp) as initial_geoip_time_zone,

    -- attribution
    argMinState({referring_domain}, timestamp) as initial_referring_domain,
    argMinState({utm_source}, timestamp) as initial_utm_source,
    argMinState({utm_campaign}, timestamp) as initial_utm_campaign,
    argMinState({utm_medium}, timestamp) as initial_utm_medium,
    argMinState({utm_term}, timestamp) as initial_utm_term,
    argMinState({utm_content}, timestamp) as initial_utm_content,
    argMinState({gclid}, timestamp) as initial_gclid,
    argMinState({gad_source}, timestamp) as initial_gad_source,
    argMinState({gclsrc}, timestamp) as initial_gclsrc,
    argMinState({dclid}, timestamp) as initial_dclid,
    argMinState({gbraid}, timestamp) as initial_gbraid,
    argMinState({wbraid}, timestamp) as initial_wbraid,
    argMinState({fbclid}, timestamp) as initial_fbclid,
    argMinState({msclkid}, timestamp) as initial_msclkid,
    argMinState({twclid}, timestamp) as initial_twclid,
    argMinState({li_fat_id}, timestamp) as initial_li_fat_id,
    argMinState({mc_cid}, timestamp) as initial_mc_cid,
    argMinState({igshid}, timestamp) as initial_igshid,
    argMinState({ttclid}, timestamp) as initial_ttclid,
    argMinState({epik}, timestamp) as initial_epik,
    argMinState({qclid}, timestamp) as initial_qclid,
    argMinState({sccid}, timestamp) as initial_sccid,
    argMinState({kx}, timestamp) as initial__kx,
    argMinState({irclid}, timestamp) as initial_irclid,

    -- count
    sumIf(1, event='$pageview') as pageview_count,
    uniqState(CAST(if(event='$pageview', uuid, NULL) AS Nullable(UUID))) as pageview_uniq,
    sumIf(1, event='$autocapture') as autocapture_count,
    uniqState(CAST(if(event='$autocapture', uuid, NULL) AS Nullable(UUID))) as autocapture_uniq,
    sumIf(1, event='$screen') as screen_count,
    uniqState(CAST(if(event='$screen', uuid, NULL) AS Nullable(UUID))) as screen_uniq,

    -- replay
    false as maybe_has_session_replay,

    -- perf
    uniqUpToState(1)(CAST(if(event='$pageview' OR event='$screen' OR event='$autocapture', uuid, NULL) AS Nullable(UUID))) as page_screen_autocapture_uniq_up_to,

    -- web vitals
    argMinState({vitals_lcp}, timestamp) as vitals_lcp
FROM {database}.sharded_events
WHERE bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(`$session_id`, 'UUID')), 76), 0xF) == 7 -- has a session id and is valid uuidv7)
GROUP BY
    team_id,
    toStartOfHour(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000))),
    cityHash64(session_id_v7),
    session_id_v7
""".format(
        database=settings.CLICKHOUSE_DATABASE,
        current_url=source_url_column("$current_url"),
        current_url_string=source_string_column("$current_url"),
        external_click_url=source_string_column("$external_click_url"),
        referring_domain=source_string_column("$referring_domain"),
        browser=source_string_column("$browser"),
        browser_version=source_string_column("$browser_version"),
        os=source_string_column("$os"),
        os_version=source_string_column("$os_version"),
        device_type=source_string_column("$device_type"),
        viewport_width=source_int_column("$viewport_width"),
        viewport_height=source_int_column("$viewport_height"),
        geoip_country_code=source_string_column("$geoip_country_code"),
        geoip_subdivision_1_code=source_string_column("$geoip_subdivision_1_code"),
        geoip_subdivision_1_name=source_string_column("$geoip_subdivision_1_name"),
        geoip_subdivision_city_name=source_string_column("$geoip_subdivision_city_name"),
        geoip_time_zone=source_string_column("$geoip_time_zone"),
        utm_source=source_string_column("utm_source"),
        utm_campaign=source_string_column("utm_campaign"),
        utm_medium=source_string_column("utm_medium"),
        utm_term=source_string_column("utm_term"),
        utm_content=source_string_column("utm_content"),
        gclid=source_string_column("gclid"),
        gad_source=source_string_column("gad_source"),
        gclsrc=source_string_column("gclsrc"),
        dclid=source_string_column("dclid"),
        gbraid=source_string_column("gbraid"),
        wbraid=source_string_column("wbraid"),
        fbclid=source_string_column("fbclid"),
        msclkid=source_string_column("msclkid"),
        twclid=source_string_column("twclid"),
        li_fat_id=source_string_column("li_fat_id"),
        mc_cid=source_string_column("mc_cid"),
        igshid=source_string_column("igshid"),
        ttclid=source_string_column("ttclid"),
        epik=source_string_column("epik"),
        qclid=source_string_column("qclid"),
        sccid=source_string_column("sccid"),
        kx=source_string_column("_kx"),
        irclid=source_string_column("irclid"),
        vitals_lcp=source_nullable_float_column("$web_vitals_LCP_value"),
    )
)

RAW_SESSIONS_TABLE_MV_SQL = (
    lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS {table_name} {on_cluster_clause}
TO {database}.{target_table}
AS
{select_sql}
""".format(
        table_name=f"{TABLE_BASE_NAME}_mv",
        target_table=f"writable_{TABLE_BASE_NAME}",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster=False),
        database=settings.CLICKHOUSE_DATABASE,
        select_sql=RAW_SESSION_TABLE_MV_SELECT_SQL(),
    )
)

RAW_SESSION_TABLE_UPDATE_SQL = (
    lambda: """
ALTER TABLE {table_name} {on_cluster_clause}
MODIFY QUERY
{select_sql}
""".format(
        table_name=f"{TABLE_BASE_NAME}_mv",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster=False),
        select_sql=RAW_SESSION_TABLE_MV_SELECT_SQL(),
    )
)

# Distributed engine tables are only created if CLICKHOUSE_REPLICATED

# This table is responsible for writing to sharded_sessions based on a sharding key.


def WRITABLE_RAW_SESSIONS_TABLE_SQL(on_cluster=True):
    return RAW_SESSIONS_TABLE_BASE_SQL.format(
        table_name=WRITABLE_RAW_SESSIONS_DATA_TABLE(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=SHARDED_RAW_SESSIONS_DATA_TABLE(),
            # shard via session_id so that all events for a session are on the same shard
            sharding_key="cityHash64(session_id_v7)",
        ),
    )


# This table is responsible for reading from sessions on a cluster setting


def DISTRIBUTED_RAW_SESSIONS_TABLE_SQL(on_cluster=True):
    return RAW_SESSIONS_TABLE_BASE_SQL.format(
        table_name=TABLE_BASE_NAME,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=SHARDED_RAW_SESSIONS_DATA_TABLE(),
            sharding_key="cityHash64(session_id_v7)",
        ),
    )


# This is the view that can be queried directly, that handles aggregation of potentially multiple rows per session.
# Most queries won't use this directly as they will want to pre-filter rows before aggregation, but it's useful for
# debugging
RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL = (
    lambda: f"""
CREATE OR REPLACE VIEW {TABLE_BASE_NAME}_v {ON_CLUSTER_CLAUSE(on_cluster=False)} AS
SELECT
    session_id_v7,
    fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000)) as session_timestamp,
    team_id,
    argMaxMerge(distinct_id) as distinct_id,
    min(min_timestamp) as min_timestamp,
    max(max_timestamp) as max_timestamp,
    max(max_inserted_at) as max_inserted_at,

    -- urls
    arrayDistinct(arrayFlatten(groupArray(urls)) )AS urls,
    argMinMerge(entry_url) as entry_url,
    argMaxMerge(end_url) as end_url,
    argMaxMerge(last_external_click_url) as last_external_click_url,

    -- device
    argMinMerge(initial_browser) as initial_browser,
    argMinMerge(initial_browser_version) as initial_browser_version,
    argMinMerge(initial_os) as initial_os,
    argMinMerge(initial_os_version) as initial_os_version,
    argMinMerge(initial_device_type) as initial_device_type,
    argMinMerge(initial_viewport_width) as initial_viewport_width,
    argMinMerge(initial_viewport_height) as initial_viewport_height,

    -- geoip
    argMinMerge(initial_geoip_country_code) as initial_geoip_country_code,
    argMinMerge(initial_geoip_subdivision_1_code) as initial_geoip_subdivision_1_code,
    argMinMerge(initial_geoip_subdivision_1_name) as initial_geoip_subdivision_1_name,
    argMinMerge(initial_geoip_subdivision_city_name) as initial_geoip_subdivision_city_name,
    argMinMerge(initial_geoip_time_zone) as initial_geoip_time_zone,

    -- attribution
    argMinMerge(initial_utm_source) as initial_utm_source,
    argMinMerge(initial_utm_campaign) as initial_utm_campaign,
    argMinMerge(initial_utm_medium) as initial_utm_medium,
    argMinMerge(initial_utm_term) as initial_utm_term,
    argMinMerge(initial_utm_content) as initial_utm_content,
    argMinMerge(initial_referring_domain) as initial_referring_domain,
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
    argMinMerge(initial__kx) as initial__kx,
    argMinMerge(initial_irclid) as initial_irclid,

    sum(pageview_count) as pageview_count,
    uniqMerge(pageview_uniq) as pageview_uniq,
    sum(autocapture_count) as autocapture_count,
    uniqMerge(autocapture_uniq) as autocapture_uniq,
    sum(screen_count) as screen_count,
    uniqMerge(screen_uniq) as screen_uniq,

    max(maybe_has_session_replay) as maybe_has_session_replay,

    uniqUpToMerge(1)(page_screen_autocapture_uniq_up_to) as page_screen_autocapture_uniq_up_to,

    argMinMerge(vitals_lcp) as vitals_lcp
FROM {TABLE_BASE_NAME}
GROUP BY session_id_v7, team_id
"""
)

RAW_SELECT_SESSION_PROP_STRING_VALUES_SQL = """
SELECT
    value,
    count(value)
FROM (
    SELECT
        {property_expr} as value
    FROM
        raw_sessions
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

RAW_SELECT_SESSION_PROP_STRING_VALUES_SQL_WITH_FILTER = """
SELECT
    value,
    count(value)
FROM (
    SELECT
        {property_expr} as value
    FROM
        raw_sessions
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

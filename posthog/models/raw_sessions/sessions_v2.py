from django.conf import settings

from posthog.hogql.escape_sql import escape_clickhouse_identifier

from posthog.clickhouse.events_json import EVENTS_PROPERTIES_JSON_SUBCOLUMNS
from posthog.models.event.new_events_schema import events_read_table, use_new_events_schema


def source_string_column(column_name: str, use_new: bool = False) -> str:
    if use_new:
        column = f"properties.{escape_clickhouse_identifier(column_name)}"
        if column_name not in EVENTS_PROPERTIES_JSON_SUBCOLUMNS:
            column = f"CAST({column}, 'Nullable(String)')"
        return f"CAST(ifNull({column}, ''), 'String')"
    return f"JSONExtractString(properties, '{column_name}')"


def source_url_column(column_name: str, use_new: bool = False) -> str:
    return f"nullIf({source_string_column(column_name, use_new)}, '')"


def source_int_column(column_name: str, use_new: bool = False) -> str:
    if use_new:
        return f"JSONExtractInt({source_string_column(column_name, use_new)})"
    return f"JSONExtractInt(properties, '{column_name}')"


def source_nullable_float_column(column_name: str, use_new: bool = False) -> str:
    if use_new:
        return f"accurateCastOrNull({source_string_column(column_name, use_new)}, 'Float64')"
    # this is what we do in queries, but it seems pretty awful
    return f"""accurateCastOrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, '{column_name}'), ''), 'null'), '^"|"$', ''), 'Float64')"""


def RAW_SESSION_TABLE_BACKFILL_SELECT_SQL(
    team_id: int | None = None,
    *,
    events_table: str | None = None,
    session_id_expr: str | None = None,
) -> str:
    use_new = events_table is None and use_new_events_schema(team_id)
    if session_id_expr is None:
        session_id_expr = "properties.`$session_id`" if use_new else "`$session_id`"
    events_table = events_table or events_read_table(use_new)

    return """
SELECT
    team_id,
    toUInt128(toUUID({session_id})) as session_id_v7,

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
FROM {database}.{events_table}
WHERE bitAnd(bitShiftRight(toUInt128(accurateCastOrNull({session_id}, 'UUID')), 76), 0xF) == 7 -- has a session id and is valid uuidv7
""".format(
        database=settings.CLICKHOUSE_DATABASE,
        events_table=events_table,
        session_id=session_id_expr,
        current_url=source_url_column("$current_url", use_new),
        current_url_string=source_string_column("$current_url", use_new),
        external_click_url=source_string_column("$external_click_url", use_new),
        browser=source_string_column("$browser", use_new),
        browser_version=source_string_column("$browser_version", use_new),
        os=source_string_column("$os", use_new),
        os_version=source_string_column("$os_version", use_new),
        device_type=source_string_column("$device_type", use_new),
        viewport_width=source_int_column("$viewport_width", use_new),
        viewport_height=source_int_column("$viewport_height", use_new),
        geoip_country_code=source_string_column("$geoip_country_code", use_new),
        geoip_subdivision_1_code=source_string_column("$geoip_subdivision_1_code", use_new),
        geoip_subdivision_1_name=source_string_column("$geoip_subdivision_1_name", use_new),
        geoip_subdivision_city_name=source_string_column("$geoip_subdivision_city_name", use_new),
        geoip_time_zone=source_string_column("$geoip_time_zone", use_new),
        referring_domain=source_string_column("$referring_domain", use_new),
        utm_source=source_string_column("utm_source", use_new),
        utm_campaign=source_string_column("utm_campaign", use_new),
        utm_medium=source_string_column("utm_medium", use_new),
        utm_term=source_string_column("utm_term", use_new),
        utm_content=source_string_column("utm_content", use_new),
        gclid=source_string_column("gclid", use_new),
        gad_source=source_string_column("gad_source", use_new),
        gclsrc=source_string_column("gclsrc", use_new),
        dclid=source_string_column("dclid", use_new),
        gbraid=source_string_column("gbraid", use_new),
        wbraid=source_string_column("wbraid", use_new),
        fbclid=source_string_column("fbclid", use_new),
        msclkid=source_string_column("msclkid", use_new),
        twclid=source_string_column("twclid", use_new),
        li_fat_id=source_string_column("li_fat_id", use_new),
        mc_cid=source_string_column("mc_cid", use_new),
        igshid=source_string_column("igshid", use_new),
        ttclid=source_string_column("ttclid", use_new),
        epik=source_string_column("epik", use_new),
        qclid=source_string_column("qclid", use_new),
        sccid=source_string_column("sccid", use_new),
        kx=source_string_column("_kx", use_new),
        irclid=source_string_column("irclid", use_new),
        vitals_lcp=source_nullable_float_column("$web_vitals_LCP_value", use_new),
    )

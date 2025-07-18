from posthog.clickhouse.table_engines import MergeTreeEngine, ReplicationScheme
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.hogql.database.schema.web_analytics_s3 import get_s3_function_args


def TABLE_TEMPLATE(table_name, columns, order_by):
    engine = MergeTreeEngine(table_name, replication_scheme=ReplicationScheme.REPLICATED)

    return f"""
    CREATE TABLE IF NOT EXISTS {table_name} {ON_CLUSTER_CLAUSE(on_cluster=True)}
    (
        period_bucket DateTime,
        team_id UInt64,
        host String,
        device_type String,
        {columns}
    ) ENGINE = {engine}
    PARTITION BY toYYYYMMDD(period_bucket)
    ORDER BY {order_by}
    """


def HOURLY_TABLE_TEMPLATE(table_name, columns, order_by, ttl=None):
    engine = MergeTreeEngine(table_name, replication_scheme=ReplicationScheme.REPLICATED)

    ttl_clause = f"TTL period_bucket + INTERVAL {ttl} DELETE" if ttl else ""

    return f"""
    CREATE TABLE IF NOT EXISTS {table_name} {ON_CLUSTER_CLAUSE(on_cluster=True)}
    (
        period_bucket DateTime,
        team_id UInt64,
        host String,
        device_type String,
        {columns}
    ) ENGINE = {engine}
    ORDER BY {order_by}
    PARTITION BY formatDateTime(period_bucket, '%Y%m%d%H')
    {ttl_clause}
    """


WEB_ANALYTICS_DIMENSIONS = [
    "entry_pathname",
    "end_pathname",
    "browser",
    "os",
    "viewport_width",
    "viewport_height",
    "referring_domain",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "country_code",
    "city_name",
    "region_code",
    "region_name",
]


WEB_STATS_DIMENSIONS = ["pathname", *WEB_ANALYTICS_DIMENSIONS]
WEB_BOUNCES_DIMENSIONS = WEB_ANALYTICS_DIMENSIONS


def get_dimension_columns(dimensions):
    column_definitions = []
    for d in dimensions:
        if d in ["viewport_width", "viewport_height"]:
            column_definitions.append(f"{d} Int64")
        else:
            column_definitions.append(f"{d} String")
    return ",\n".join(column_definitions)


def get_order_by_clause(dimensions, bucket_column="period_bucket"):
    base_columns = ["team_id", bucket_column, "host", "device_type"]
    all_columns = base_columns + dimensions
    column_list = ",\n    ".join(all_columns)
    return f"(\n    {column_list}\n)"


WEB_STATS_COLUMNS = f"""
    {get_dimension_columns(WEB_STATS_DIMENSIONS)},
    persons_uniq_state AggregateFunction(uniq, UUID),
    sessions_uniq_state AggregateFunction(uniq, String),
    pageviews_count_state AggregateFunction(sum, UInt64),
"""

WEB_BOUNCES_COLUMNS = f"""
    {get_dimension_columns(WEB_BOUNCES_DIMENSIONS)},
    persons_uniq_state AggregateFunction(uniq, UUID),
    sessions_uniq_state AggregateFunction(uniq, String),
    pageviews_count_state AggregateFunction(sum, UInt64),
    bounces_count_state AggregateFunction(sum, UInt64),
    total_session_duration_state AggregateFunction(sum, Int64),
    total_session_count_state AggregateFunction(sum, UInt64)
"""


def WEB_STATS_ORDER_BY_FUNC(bucket_column="period_bucket"):
    return get_order_by_clause(WEB_STATS_DIMENSIONS, bucket_column)


def WEB_BOUNCES_ORDER_BY_FUNC(bucket_column="period_bucket"):
    return get_order_by_clause(WEB_BOUNCES_DIMENSIONS, bucket_column)


def DROP_PARTITION_SQL(table_name, date_start, granularity="daily"):
    """
    Generate SQL to drop a partition for a specific date.
    This enables idempotent operations by ensuring clean state before insertion.

    Args:
        table_name: Name of the table
        date_start: Date string in YYYY-MM-DD format (for daily) or YYYY-MM-DD HH format (for hourly)
        granularity: "daily" or "hourly" - determines partition format
    """

    if granularity == "hourly":
        # For hourly: expect "YYYY-MM-DD HH" format, convert to "YYYYMMDDHH"
        if " " in date_start:
            date_part, hour_part = date_start.split(" ")
            partition_id = date_part.replace("-", "") + hour_part.zfill(2)
        else:
            # If only date provided for hourly, format as "YYYYMMDD00"
            partition_id = date_start.replace("-", "") + "00"
    else:
        # For daily: format date as YYYYMMDD
        partition_id = date_start.replace("-", "")

    return f"""
    ALTER TABLE {table_name}
    DROP PARTITION '{partition_id}'
    """


def WEB_STATS_DAILY_SQL(table_name="web_stats_daily"):
    return TABLE_TEMPLATE(table_name, WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC("period_bucket"))


def WEB_BOUNCES_DAILY_SQL(table_name="web_bounces_daily"):
    return TABLE_TEMPLATE(table_name, WEB_BOUNCES_COLUMNS, WEB_BOUNCES_ORDER_BY_FUNC("period_bucket"))


def WEB_STATS_HOURLY_SQL():
    return HOURLY_TABLE_TEMPLATE(
        "web_stats_hourly", WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC("period_bucket"), ttl="24 HOUR"
    )


def WEB_BOUNCES_HOURLY_SQL():
    return HOURLY_TABLE_TEMPLATE(
        "web_bounces_hourly", WEB_BOUNCES_COLUMNS, WEB_BOUNCES_ORDER_BY_FUNC("period_bucket"), ttl="24 HOUR"
    )


def format_team_ids(team_ids):
    return ", ".join(str(team_id) for team_id in team_ids)


def get_team_filters(team_ids):
    team_ids_str = format_team_ids(team_ids) if team_ids else None
    return {
        "raw_sessions": f"raw_sessions.team_id IN({team_ids_str})" if team_ids else "1=1",
        "person_distinct_id_overrides": (
            f"person_distinct_id_overrides.team_id IN({team_ids_str})" if team_ids else "1=1"
        ),
        "events": f"e.team_id IN({team_ids_str})" if team_ids else "1=1",
    }


def get_insert_params(team_ids, granularity="daily"):
    filters = get_team_filters(team_ids)

    if granularity == "hourly":
        time_bucket_func = "toStartOfHour"
        bucket_column = "period_bucket"
    else:
        time_bucket_func = "toStartOfDay"
        bucket_column = "period_bucket"

    return {
        "team_filter": filters["raw_sessions"],
        "person_team_filter": filters["person_distinct_id_overrides"],
        "events_team_filter": filters["events"],
        "time_bucket_func": time_bucket_func,
        "bucket_column": bucket_column,
    }


def WEB_STATS_INSERT_SQL(
    date_start,
    date_end,
    team_ids=None,
    timezone="UTC",
    settings="",
    table_name="web_stats_daily",
    granularity="daily",
    select_only=False,
):
    params = get_insert_params(team_ids, granularity)
    team_filter = params["team_filter"]
    person_team_filter = params["person_team_filter"]
    events_team_filter = params["events_team_filter"]
    time_bucket_func = params["time_bucket_func"]
    settings_clause = f"SETTINGS {settings}" if settings else ""

    query = f"""
    SELECT
        {time_bucket_func}(start_timestamp) AS period_bucket,
        team_id,
        host,
        device_type,
        entry_pathname,
        pathname,
        end_pathname,
        browser,
        os,
        viewport_width,
        viewport_height,
        referring_domain,
        utm_source,
        utm_medium,
        utm_campaign,
        utm_term,
        utm_content,
        country_code,
        city_name,
        region_code,
        region_name,
        uniqState(assumeNotNull(session_person_id)) AS persons_uniq_state,
        uniqState(assumeNotNull(session_id)) AS sessions_uniq_state,
        sumState(pageview_count) AS pageviews_count_state
    FROM
    (
        SELECT
            any(if(NOT empty(events__override.distinct_id), events__override.person_id, events.person_id)) AS session_person_id,
            events__session.session_id AS session_id,
            e.mat_$host AS host,
            e.mat_$device_type AS device_type,
            e.mat_$browser AS browser,
            e.mat_$os AS os,
            accurateCastOrNull(e.mat_$viewport_width, 'Int64') AS viewport_width,
            accurateCastOrNull(e.mat_$viewport_height, 'Int64') AS viewport_height,
            e.mat_$geoip_country_code AS country_code,
            e.mat_$geoip_city_name AS city_name,
            e.mat_$geoip_subdivision_1_code AS region_code,
            e.mat_$pathname AS pathname,
            events__session.entry_utm_source AS utm_source,
            events__session.entry_utm_medium AS utm_medium,
            events__session.entry_utm_campaign AS utm_campaign,
            events__session.entry_utm_term AS utm_term,
            events__session.entry_utm_content AS utm_content,
            events__session.entry_pathname AS entry_pathname,
            events__session.end_pathname AS end_pathname,
            events__session.referring_domain AS referring_domain,
            events__session.region_name AS region_name,
            countIf(e.event IN ('$pageview', '$screen')) AS pageview_count,
            e.team_id AS team_id,
            min(events__session.start_timestamp) AS start_timestamp
        FROM events AS e
        LEFT JOIN
        (
            SELECT
                toString(reinterpretAsUUID(bitOr(bitShiftLeft(raw_sessions.session_id_v7, 64), bitShiftRight(raw_sessions.session_id_v7, 64)))) AS session_id,
                min(toTimeZone(raw_sessions.min_timestamp, '{timezone}')) AS start_timestamp,
                path(coalesce(argMinMerge(raw_sessions.entry_url), '')) AS entry_pathname,
                path(coalesce(argMaxMerge(raw_sessions.end_url), '')) AS end_pathname,
                argMinMerge(raw_sessions.initial_referring_domain) AS referring_domain,
                argMinMerge(raw_sessions.initial_utm_source) AS entry_utm_source,
                argMinMerge(raw_sessions.initial_utm_medium) AS entry_utm_medium,
                argMinMerge(raw_sessions.initial_utm_campaign) AS entry_utm_campaign,
                argMinMerge(raw_sessions.initial_utm_term) AS entry_utm_term,
                argMinMerge(raw_sessions.initial_utm_content) AS entry_utm_content,
                argMinMerge(raw_sessions.initial_geoip_country_code) AS country_code,
                argMinMerge(raw_sessions.initial_geoip_subdivision_1_code) AS region_code,
                argMinMerge(raw_sessions.initial_geoip_subdivision_1_name) AS region_name,
                argMinMerge(raw_sessions.initial_geoip_subdivision_city_name) AS city_name,
                raw_sessions.session_id_v7 AS session_id_v7
            FROM raw_sessions
            WHERE {team_filter}
                AND fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= minus(toDateTime('{date_start}', '{timezone}'), toIntervalHour(24))
                AND fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) <= toDateTime('{date_end}', '{timezone}')
            GROUP BY
                raw_sessions.session_id_v7
            {settings_clause}
        ) AS events__session ON toUInt128(accurateCastOrNull(e.`$session_id`, 'UUID')) = events__session.session_id_v7
        LEFT JOIN
        (
            SELECT
                argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
                person_distinct_id_overrides.distinct_id AS distinct_id
            FROM person_distinct_id_overrides
            WHERE {person_team_filter}
            GROUP BY person_distinct_id_overrides.distinct_id
            HAVING ifNull(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version) = 0, 0)
            {settings_clause}
        ) AS events__override ON e.distinct_id = events__override.distinct_id
        WHERE {events_team_filter}
            AND ((e.event = '$pageview') OR (e.event = '$screen'))
            AND (e.`$session_id` IS NOT NULL)
            AND toTimeZone(e.timestamp, '{timezone}') >= toDateTime('{date_start}', '{timezone}')
            AND toTimeZone(e.timestamp, '{timezone}') < toDateTime('{date_end}', '{timezone}')
        GROUP BY
            events__session.session_id,
            e.team_id,
            host,
            device_type,
            browser,
            os,
            viewport_width,
            viewport_height,
            referring_domain,
            utm_source,
            utm_medium,
            utm_campaign,
            utm_term,
            utm_content,
            pathname,
            entry_pathname,
            end_pathname,
            country_code,
            city_name,
            region_code,
            region_name
        {settings_clause}
    )
    GROUP BY
        period_bucket,
        team_id,
        host,
        device_type,
        browser,
        os,
        viewport_width,
        viewport_height,
        referring_domain,
        utm_source,
        utm_medium,
        utm_campaign,
        utm_term,
        utm_content,
        pathname,
        entry_pathname,
        end_pathname,
        country_code,
        city_name,
        region_code,
        region_name
    {settings_clause}
    """

    if select_only:
        return query
    else:
        return f"INSERT INTO {table_name}\n{query}"


def WEB_BOUNCES_INSERT_SQL(
    date_start,
    date_end,
    team_ids=None,
    timezone="UTC",
    settings="",
    table_name="web_bounces_daily",
    granularity="daily",
    select_only=False,
):
    params = get_insert_params(team_ids, granularity)
    team_filter = params["team_filter"]
    person_team_filter = params["person_team_filter"]
    events_team_filter = params["events_team_filter"]
    time_bucket_func = params["time_bucket_func"]

    settings_clause = f"SETTINGS {settings}" if settings else ""

    query = f"""
    SELECT
        {time_bucket_func}(start_timestamp) AS period_bucket,
        team_id,
        host,
        device_type,
        entry_pathname,
        end_pathname,
        browser,
        os,
        viewport_width,
        viewport_height,
        referring_domain,
        utm_source,
        utm_medium,
        utm_campaign,
        utm_term,
        utm_content,
        country_code,
        city_name,
        region_code,
        region_name,
        uniqState(assumeNotNull(person_id)) AS persons_uniq_state,
        uniqState(assumeNotNull(session_id)) AS sessions_uniq_state,
        sumState(pageview_count) AS pageviews_count_state,
        sumState(toUInt64(ifNull(is_bounce, 0))) AS bounces_count_state,
        sumState(session_duration) AS total_session_duration_state,
        sumState(total_session_count_state) AS total_session_count_state
    FROM
    (
        SELECT
            argMax(if(NOT empty(events__override.distinct_id), events__override.person_id, events.person_id), e.timestamp) AS person_id,
            countIf(e.event IN ('$pageview', '$screen')) AS pageview_count,
            any(events__session.entry_pathname) AS entry_pathname,
            any(events__session.end_pathname) AS end_pathname,
            any(events__session.referring_domain) AS referring_domain,
            any(events__session.entry_utm_source) AS utm_source,
            any(events__session.entry_utm_medium) AS utm_medium,
            any(events__session.entry_utm_campaign) AS utm_campaign,
            any(events__session.entry_utm_term) AS utm_term,
            any(events__session.entry_utm_content) AS utm_content,
            any(events__session.country_code) AS country_code,
            any(events__session.city_name) AS city_name,
            any(events__session.region_code) AS region_code,
            any(events__session.region_name) AS region_name,
            any(e.mat_$host) AS host,
            any(e.mat_$device_type) AS device_type,
            any(e.mat_$browser) AS browser,
            any(e.mat_$os) AS os,
            accurateCastOrNull(any(e.mat_$viewport_width), 'Int64') AS viewport_width,
            accurateCastOrNull(any(e.mat_$viewport_height), 'Int64') AS viewport_height,
            any(events__session.is_bounce) AS is_bounce,
            any(events__session.session_duration) AS session_duration,
            toUInt64(1) AS total_session_count_state,
            events__session.session_id AS session_id,
            e.team_id AS team_id,
            min(events__session.start_timestamp) AS start_timestamp
        FROM events AS e
        LEFT JOIN
        (
            SELECT
                path(coalesce(argMinMerge(raw_sessions.entry_url), '')) AS entry_pathname,
                path(coalesce(argMaxMerge(raw_sessions.end_url), '')) AS end_pathname,
                argMinMerge(raw_sessions.initial_referring_domain) AS referring_domain,
                argMinMerge(raw_sessions.initial_utm_source) AS entry_utm_source,
                argMinMerge(raw_sessions.initial_utm_medium) AS entry_utm_medium,
                argMinMerge(raw_sessions.initial_utm_campaign) AS entry_utm_campaign,
                argMinMerge(raw_sessions.initial_utm_term) AS entry_utm_term,
                argMinMerge(raw_sessions.initial_utm_content) AS entry_utm_content,
                argMinMerge(raw_sessions.initial_geoip_country_code) AS country_code,
                argMinMerge(raw_sessions.initial_geoip_subdivision_city_name) AS city_name,
                argMinMerge(raw_sessions.initial_geoip_subdivision_1_code) AS region_code,
                argMinMerge(raw_sessions.initial_geoip_subdivision_1_name) AS region_name,
                toString(reinterpretAsUUID(bitOr(bitShiftLeft(raw_sessions.session_id_v7, 64), bitShiftRight(raw_sessions.session_id_v7, 64)))) AS session_id,
                dateDiff('second', min(toTimeZone(raw_sessions.min_timestamp, '{timezone}')), max(toTimeZone(raw_sessions.max_timestamp, '{timezone}'))) AS session_duration,
                if(ifNull(equals(uniqUpToMerge(1)(raw_sessions.page_screen_autocapture_uniq_up_to), 0), 0), NULL,
                    NOT(or(
                        ifNull(greater(uniqUpToMerge(1)(raw_sessions.page_screen_autocapture_uniq_up_to), 1), 0),
                        greaterOrEquals(dateDiff('second',
                        min(toTimeZone(raw_sessions.min_timestamp, '{timezone}')),
                        max(toTimeZone(raw_sessions.max_timestamp, '{timezone}'))), 10)
                    ))
                ) AS is_bounce,
                min(toTimeZone(raw_sessions.min_timestamp, '{timezone}')) AS start_timestamp,
                raw_sessions.session_id_v7 AS session_id_v7
            FROM raw_sessions
            WHERE {team_filter}
                AND fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= minus(toDateTime('{date_start}', '{timezone}'), toIntervalHour(24))
                AND fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) <= toDateTime('{date_end}', '{timezone}')
            GROUP BY raw_sessions.session_id_v7
        ) AS events__session ON toUInt128(accurateCastOrNull(e.`$session_id`, 'UUID')) = events__session.session_id_v7
        LEFT JOIN
        (
            SELECT
                argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
                person_distinct_id_overrides.distinct_id AS distinct_id
            FROM person_distinct_id_overrides
            WHERE {person_team_filter}
            GROUP BY person_distinct_id_overrides.distinct_id
            HAVING ifNull(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version) = 0, 0)
        ) AS events__override ON e.distinct_id = events__override.distinct_id
        WHERE {events_team_filter}
            AND ((e.event = '$pageview') OR (e.event = '$screen'))
            AND (e.`$session_id` IS NOT NULL)
            AND toTimeZone(e.timestamp, '{timezone}') >= toDateTime('{date_start}', '{timezone}')
            AND toTimeZone(e.timestamp, '{timezone}') < toDateTime('{date_end}', '{timezone}')
        GROUP BY
            session_id,
            team_id
    )
    GROUP BY
        period_bucket,
        team_id,
        host,
        device_type,
        entry_pathname,
        end_pathname,
        referring_domain,
        utm_source,
        utm_medium,
        utm_campaign,
        utm_term,
        utm_content,
        country_code,
        city_name,
        region_code,
        region_name,
        browser,
        os,
        viewport_width,
        viewport_height
    {settings_clause}
    """

    if select_only:
        return query
    else:
        return f"INSERT INTO {table_name}\n{query}"


def WEB_STATS_EXPORT_SQL(
    date_start, date_end, team_ids=None, timezone="UTC", settings="", table_name="web_stats_daily", s3_path=None
):
    team_ids_filter = ""
    if team_ids:
        team_ids_str = format_team_ids(team_ids)
        team_ids_filter = f"AND team_id IN ({team_ids_str})"

    if not s3_path:
        raise ValueError("s3_path is required")

    s3_function_args = get_s3_function_args(s3_path)

    return f"""
    INSERT INTO FUNCTION s3({s3_function_args})
    SELECT
        period_bucket,
        team_id,
        persons_uniq_state,
        sessions_uniq_state,
        pageviews_count_state
    FROM {table_name}
    WHERE period_bucket >= toDateTime('{date_start}', '{timezone}')
        AND period_bucket < toDateTime('{date_end}', '{timezone}')
        {team_ids_filter}
    GROUP BY team_id, period_bucket, persons_uniq_state, sessions_uniq_state, pageviews_count_state
    ORDER BY team_id, period_bucket
    SETTINGS {settings}
    """


def WEB_BOUNCES_EXPORT_SQL(
    date_start, date_end, team_ids=None, timezone="UTC", settings="", table_name="web_bounces_daily", s3_path=None
):
    team_ids_filter = ""
    if team_ids:
        team_ids_str = format_team_ids(team_ids)
        team_ids_filter = f"AND team_id IN ({team_ids_str})"

    if not s3_path:
        raise ValueError("s3_path is required")

    s3_function_args = get_s3_function_args(s3_path)

    return f"""
    INSERT INTO FUNCTION s3({s3_function_args})
    SELECT
        period_bucket,
        team_id,
        persons_uniq_state,
        sessions_uniq_state,
        pageviews_count_state,
        bounces_count_state,
        total_session_duration_state
    FROM {table_name}
    WHERE period_bucket >= toDateTime('{date_start}', '{timezone}')
        AND period_bucket < toDateTime('{date_end}', '{timezone}')
        {team_ids_filter}
    GROUP BY period_bucket, team_id, persons_uniq_state, sessions_uniq_state, pageviews_count_state, bounces_count_state, total_session_duration_state
    ORDER BY team_id, period_bucket
    SETTINGS {settings}
    """


def create_combined_view_sql(table_prefix):
    return f"""
    CREATE VIEW IF NOT EXISTS {table_prefix}_combined AS
    SELECT * FROM {table_prefix}_daily WHERE period_bucket < toStartOfDay(now(), 'UTC')
    UNION ALL
    SELECT * FROM {table_prefix}_hourly WHERE period_bucket >= toStartOfDay(now(), 'UTC')
    """


def WEB_STATS_COMBINED_VIEW_SQL():
    return create_combined_view_sql("web_stats")


def WEB_BOUNCES_COMBINED_VIEW_SQL():
    return create_combined_view_sql("web_bounces")

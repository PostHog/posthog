import uuid

from django.conf import settings

from posthog.hogql.database.schema.web_analytics_s3 import get_s3_function_args

from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import MergeTreeEngine, ReplicationScheme
from posthog.models.web_preaggregated.team_selection import WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_NAME


def is_eu_cluster() -> bool:
    return getattr(settings, "CLOUD_DEPLOYMENT", None) == "EU"


def TABLE_TEMPLATE(table_name, columns, order_by, on_cluster=True, force_unique_zk_path=False, replace=False):
    engine = MergeTreeEngine(table_name, replication_scheme=ReplicationScheme.REPLICATED)
    if force_unique_zk_path:
        engine.set_zookeeper_path_key(str(uuid.uuid4()))

    return f"""
    {f"REPLACE TABLE {table_name}" if replace else f"CREATE TABLE IF NOT EXISTS {table_name}"} {ON_CLUSTER_CLAUSE(on_cluster=on_cluster)}
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


def HOURLY_TABLE_TEMPLATE(
    table_name, columns, order_by, ttl=None, on_cluster=True, force_unique_zk_path=False, replace=False
):
    engine = MergeTreeEngine(table_name, replication_scheme=ReplicationScheme.REPLICATED)
    if force_unique_zk_path:
        engine.set_zookeeper_path_key(str(uuid.uuid4()))

    ttl_clause = f"TTL period_bucket + INTERVAL {ttl} DELETE" if ttl else ""

    return f"""
    {f"REPLACE TABLE {table_name}" if replace else f"CREATE TABLE IF NOT EXISTS {table_name}"} {ON_CLUSTER_CLAUSE(on_cluster=on_cluster)}
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


def _DROP_TABLE_TEMPLATE(table_name: str):
    return f"DROP TABLE IF EXISTS {table_name} {ON_CLUSTER_CLAUSE()}"


def DROP_WEB_STATS_SQL():
    return _DROP_TABLE_TEMPLATE("web_pre_aggregated_stats")


def DROP_WEB_BOUNCES_SQL():
    return _DROP_TABLE_TEMPLATE("web_pre_aggregated_bounces")


def DROP_WEB_STATS_DAILY_SQL():
    return _DROP_TABLE_TEMPLATE("web_stats_daily")


def DROP_WEB_BOUNCES_DAILY_SQL():
    return _DROP_TABLE_TEMPLATE("web_bounces_daily")


def DROP_WEB_STATS_HOURLY_SQL():
    return _DROP_TABLE_TEMPLATE("web_stats_hourly")


def DROP_WEB_BOUNCES_HOURLY_SQL():
    return _DROP_TABLE_TEMPLATE("web_bounces_hourly")


def DROP_WEB_STATS_STAGING_SQL():
    return _DROP_TABLE_TEMPLATE("web_pre_aggregated_stats_staging")


def DROP_WEB_BOUNCES_STAGING_SQL():
    return _DROP_TABLE_TEMPLATE("web_pre_aggregated_bounces_staging")


def REPLACE_WEB_BOUNCES_HOURLY_STAGING_SQL():
    return HOURLY_TABLE_TEMPLATE(
        "web_bounces_hourly_staging",
        WEB_BOUNCES_COLUMNS,
        WEB_BOUNCES_ORDER_BY_FUNC("period_bucket"),
        ttl="24 HOUR",
        force_unique_zk_path=True,
        replace=True,
        on_cluster=False,
    )


def REPLACE_WEB_STATS_HOURLY_STAGING_SQL():
    return HOURLY_TABLE_TEMPLATE(
        "web_stats_hourly_staging",
        WEB_STATS_COLUMNS,
        WEB_STATS_ORDER_BY_FUNC("period_bucket"),
        ttl="24 HOUR",
        force_unique_zk_path=True,
        replace=True,
        on_cluster=False,
    )


# Hardcoded production column definitions to match exact table structure
#
# NOTE: These definitions exist because the production destination tables have a different
# column order than what our WEB_STATS_COLUMNS/WEB_BOUNCES_COLUMNS generate. Specifically,
# mat_metadata_loggedIn appears at the END of the production tables (due to migration via
# ALTER TABLE ADD COLUMN), but our code generates it in the middle. For REPLACE PARTITION
# to work, staging and destination tables must have identical column order and types.
#
# Production table schemas extracted from DESCRIBE TABLE commands:
WEB_STATS_V2_PRODUCTION_COLUMNS = """
    pathname String,
    entry_pathname String,
    end_pathname String,
    browser String,
    os String,
    viewport_width Int64,
    viewport_height Int64,
    referring_domain String,
    utm_source String,
    utm_medium String,
    utm_campaign String,
    utm_term String,
    utm_content String,
    country_code String,
    city_name String,
    region_code String,
    region_name String,
    has_gclid Bool,
    has_gad_source_paid_search Bool,
    has_fbclid Bool,
    mat_metadata_backend Nullable(String),
    persons_uniq_state AggregateFunction(uniq, UUID),
    sessions_uniq_state AggregateFunction(uniq, String),
    pageviews_count_state AggregateFunction(sum, UInt64),
    mat_metadata_loggedIn Nullable(Bool)
"""

WEB_BOUNCES_V2_PRODUCTION_COLUMNS = """
    entry_pathname String,
    end_pathname String,
    browser String,
    os String,
    viewport_width Int64,
    viewport_height Int64,
    referring_domain String,
    utm_source String,
    utm_medium String,
    utm_campaign String,
    utm_term String,
    utm_content String,
    country_code String,
    city_name String,
    region_code String,
    region_name String,
    has_gclid Bool,
    has_gad_source_paid_search Bool,
    has_fbclid Bool,
    mat_metadata_backend Nullable(String),
    persons_uniq_state AggregateFunction(uniq, UUID),
    sessions_uniq_state AggregateFunction(uniq, String),
    pageviews_count_state AggregateFunction(sum, UInt64),
    bounces_count_state AggregateFunction(sum, UInt64),
    total_session_duration_state AggregateFunction(sum, Int64),
    total_session_count_state AggregateFunction(sum, UInt64),
    mat_metadata_loggedIn Nullable(Bool)
"""

# Production ORDER BY clauses extracted from production tables
# These exclude nullable columns to avoid ClickHouse "Sorting key contains nullable columns" error
WEB_STATS_V2_PRODUCTION_ORDER_BY = """(
    team_id,
    period_bucket,
    host,
    device_type,
    pathname,
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
    has_gclid,
    has_gad_source_paid_search,
    has_fbclid
)"""

WEB_BOUNCES_V2_PRODUCTION_ORDER_BY = """(
    team_id,
    period_bucket,
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
    has_gclid,
    has_gad_source_paid_search,
    has_fbclid
)"""


def REPLACE_WEB_STATS_V2_STAGING_SQL():
    return TABLE_TEMPLATE(
        "web_pre_aggregated_stats_staging",
        WEB_STATS_V2_PRODUCTION_COLUMNS,
        WEB_STATS_V2_PRODUCTION_ORDER_BY,
        force_unique_zk_path=True,
        replace=True,
        on_cluster=False,
    )


def REPLACE_WEB_BOUNCES_V2_STAGING_SQL():
    return TABLE_TEMPLATE(
        "web_pre_aggregated_bounces_staging",
        WEB_BOUNCES_V2_PRODUCTION_COLUMNS,
        WEB_BOUNCES_V2_PRODUCTION_ORDER_BY,
        force_unique_zk_path=True,
        replace=True,
        on_cluster=False,
    )


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
    "has_gclid",
    "has_gad_source_paid_search",
    "has_fbclid",
    "mat_metadata_loggedIn",
    "mat_metadata_backend",
]

WEB_STATS_DIMENSIONS = ["pathname", *WEB_ANALYTICS_DIMENSIONS]
WEB_BOUNCES_DIMENSIONS = WEB_ANALYTICS_DIMENSIONS


def get_dimension_columns(dimensions):
    column_definitions = []
    for d in dimensions:
        if d in ["viewport_width", "viewport_height"]:
            column_definitions.append(f"{d} Int64")
        elif d in ["has_gclid", "has_gad_source_paid_search", "has_fbclid", "mat_metadata_loggedIn"]:
            column_definitions.append(f"{d} Bool")
        else:
            column_definitions.append(f"{d} String")
    return ",\n".join(column_definitions)


def get_order_by_clause(dimensions, bucket_column="period_bucket"):
    base_columns = ["team_id", bucket_column, "host", "device_type"]
    all_columns = base_columns + dimensions
    column_list = ",\n    ".join(all_columns)
    return f"(\n    {column_list}\n)"


def get_insert_columns(dimensions, aggregate_columns):
    shared_columns = ["period_bucket", "team_id", "host", "device_type"]
    all_columns = shared_columns + dimensions + aggregate_columns
    return all_columns


def get_web_stats_insert_columns():
    aggregate_columns = ["persons_uniq_state", "sessions_uniq_state", "pageviews_count_state"]
    return get_insert_columns(WEB_STATS_DIMENSIONS, aggregate_columns)


def get_web_bounces_insert_columns():
    aggregate_columns = [
        "persons_uniq_state",
        "sessions_uniq_state",
        "pageviews_count_state",
        "bounces_count_state",
        "total_session_duration_state",
        "total_session_count_state",
    ]
    return get_insert_columns(WEB_BOUNCES_DIMENSIONS, aggregate_columns)


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


def WEB_STATS_DAILY_SQL(table_name="web_stats_daily", on_cluster=False):
    return TABLE_TEMPLATE(table_name, WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC("period_bucket"), on_cluster)


def WEB_BOUNCES_DAILY_SQL(table_name="web_bounces_daily", on_cluster=False):
    return TABLE_TEMPLATE(table_name, WEB_BOUNCES_COLUMNS, WEB_BOUNCES_ORDER_BY_FUNC("period_bucket"), on_cluster)


def WEB_STATS_SQL(table_name="web_pre_aggregated_stats", on_cluster=False):
    return TABLE_TEMPLATE(table_name, WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC("period_bucket"), on_cluster)


def WEB_BOUNCES_SQL(table_name="web_pre_aggregated_bounces", on_cluster=False):
    return TABLE_TEMPLATE(table_name, WEB_BOUNCES_COLUMNS, WEB_BOUNCES_ORDER_BY_FUNC("period_bucket"), on_cluster)


def WEB_STATS_HOURLY_SQL():
    return HOURLY_TABLE_TEMPLATE(
        "web_stats_hourly", WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY_FUNC("period_bucket"), ttl="24 HOUR"
    )


def WEB_BOUNCES_HOURLY_SQL():
    return HOURLY_TABLE_TEMPLATE(
        "web_bounces_hourly", WEB_BOUNCES_COLUMNS, WEB_BOUNCES_ORDER_BY_FUNC("period_bucket"), ttl="24 HOUR"
    )


def format_team_ids(team_ids: list[int]) -> str:
    return ", ".join(str(team_id) for team_id in team_ids)


def get_team_filters(team_ids: list[int] | None) -> dict[str, str]:
    if team_ids:
        team_ids_str = format_team_ids(team_ids)
        return {
            "raw_sessions": f"raw_sessions.team_id IN({team_ids_str})",
            "person_distinct_id_overrides": f"person_distinct_id_overrides.team_id IN({team_ids_str})",
            "events": f"e.team_id IN({team_ids_str})",
        }
    else:
        return {
            "raw_sessions": f"dictHas('{WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_NAME}', raw_sessions.team_id)",
            "person_distinct_id_overrides": f"dictHas('{WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_NAME}', person_distinct_id_overrides.team_id)",
            "events": f"dictHas('{WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_NAME}', e.team_id)",
        }


def get_date_filters(date_start: str, date_end: str, timezone: str, granularity: str = "daily") -> dict[str, str]:
    if granularity == "hourly":
        # For hourly buckets, extend the session window to capture all sessions
        # that might contribute to hourly buckets within the date range
        session_start = f"minus(toDateTime('{date_start}', '{timezone}'), toIntervalHour(25))"
        session_end = f"plus(toDateTime('{date_end}', '{timezone}'), toIntervalHour(1))"
        event_start = f"minus(toDateTime('{date_start}', '{timezone}'), toIntervalHour(1))"
        event_end = f"plus(toDateTime('{date_end}', '{timezone}'), toIntervalHour(1))"
    else:
        # Keep existing logic for daily granularity
        session_start = f"minus(toDateTime('{date_start}', '{timezone}'), toIntervalHour(24))"
        session_end = f"toDateTime('{date_end}', '{timezone}')"
        event_start = f"toDateTime('{date_start}', '{timezone}')"
        event_end = f"toDateTime('{date_end}', '{timezone}')"

    # Target period filters are the same for both granularities
    target_period_start = f"toDateTime('{date_start}', '{timezone}')"
    target_period_end = f"toDateTime('{date_end}', '{timezone}')"

    return {
        "session_start_filter": session_start,
        "session_end_filter": session_end,
        "event_start_filter": event_start,
        "event_end_filter": event_end,
        "target_period_start": target_period_start,
        "target_period_end": target_period_end,
    }


def get_mat_custom_fields_expressions() -> dict[str, str]:
    if is_eu_cluster():
        return {
            "mat_metadata_loggedIn_expr": "mat_metadata_loggedIn",
            "mat_metadata_loggedIn_inner_expr": "any(IF(e.mat_metadata_loggedIn IS NULL, NULL, e.mat_metadata_loggedIn = 'true')) AS mat_metadata_loggedIn",
            "mat_metadata_backend_expr": "mat_metadata_backend",
            "mat_metadata_backend_inner_expr": "any(e.mat_metadata_backend) AS mat_metadata_backend",
            "mat_custom_fields_group_by": "mat_metadata_loggedIn, mat_metadata_backend",
        }
    else:
        # Those are no-ops to keep the same query structure on US
        return {
            "mat_metadata_loggedIn_expr": "mat_metadata_loggedIn",
            "mat_metadata_loggedIn_inner_expr": "CAST(NULL AS Nullable(Bool)) AS mat_metadata_loggedIn",
            "mat_metadata_backend_expr": "mat_metadata_backend",
            "mat_metadata_backend_inner_expr": "CAST(NULL AS Nullable(String)) AS mat_metadata_backend",
            "mat_custom_fields_group_by": "mat_metadata_loggedIn, mat_metadata_backend",
        }


def get_all_filters(
    date_start: str,
    date_end: str,
    timezone: str,
    team_ids: list[int] | None = None,
    granularity: str = "daily",
    settings: str = "",
) -> dict[str, str]:
    team_filters = get_team_filters(team_ids)
    date_filters = get_date_filters(date_start, date_end, timezone, granularity)
    mat_custom_fields_expressions = get_mat_custom_fields_expressions()

    time_bucket_func = "toStartOfHour" if granularity == "hourly" else "toStartOfDay"
    settings_clause = f"SETTINGS {settings}" if settings else ""

    return {
        "team_filter": team_filters["raw_sessions"],
        "person_team_filter": team_filters["person_distinct_id_overrides"],
        "events_team_filter": team_filters["events"],
        "time_bucket_func": time_bucket_func,
        "settings_clause": settings_clause,
        "timezone": timezone,
        "date_start": date_start,
        "date_end": date_end,
        **date_filters,
        **mat_custom_fields_expressions,
        "mat_custom_fields_outer_group_by_placeholder": (
            f",\n        {mat_custom_fields_expressions['mat_custom_fields_group_by']}"
            if mat_custom_fields_expressions["mat_custom_fields_group_by"]
            else ""
        ),
    }


def WEB_STATS_INSERT_SQL(
    date_start: str,
    date_end: str,
    team_ids: list[int] | None = None,
    timezone: str = "UTC",
    settings: str = "",
    table_name: str = "web_stats_daily",
    granularity: str = "daily",
    select_only: bool = False,
) -> str:
    filters = get_all_filters(date_start, date_end, timezone, team_ids, granularity, settings)

    query = """
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
        has_gclid,
        has_gad_source_paid_search,
        has_fbclid,
        {mat_metadata_loggedIn_expr},
        {mat_metadata_backend_expr},
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
            events__session.has_gclid AS has_gclid,
            events__session.has_gad_source_paid_search AS has_gad_source_paid_search,
            events__session.has_fbclid AS has_fbclid,
            {mat_metadata_loggedIn_inner_expr},
            {mat_metadata_backend_inner_expr},
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
                notEmpty(argMinMerge(raw_sessions.initial_gclid)) AND argMinMerge(raw_sessions.initial_gclid) != 'null' AS has_gclid,
                argMinMerge(raw_sessions.initial_gad_source) = '1' AS has_gad_source_paid_search,
                notEmpty(argMinMerge(raw_sessions.initial_fbclid)) AND argMinMerge(raw_sessions.initial_fbclid) != 'null' AS has_fbclid,
                raw_sessions.session_id_v7 AS session_id_v7
            FROM raw_sessions
            WHERE {team_filter}
                AND fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= {session_start_filter}
                AND fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) <= {session_end_filter}
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
            AND toTimeZone(e.timestamp, '{timezone}') >= {event_start_filter}
            AND toTimeZone(e.timestamp, '{timezone}') < {event_end_filter}
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
            region_name,
            has_gclid,
            has_gad_source_paid_search,
            has_fbclid
        {settings_clause}
    )
    WHERE
        period_bucket >= {target_period_start}
        AND period_bucket < {target_period_end}
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
        region_name,
        has_gclid,
        has_gad_source_paid_search,
        has_fbclid{mat_custom_fields_outer_group_by_placeholder}
    {settings_clause}
    """

    formatted_query = query.format(**filters)

    if select_only:
        return formatted_query
    else:
        columns = get_web_stats_insert_columns()
        column_list = ",\n    ".join(columns)
        return f"INSERT INTO {table_name}\n(\n    {column_list}\n)\n{formatted_query}"


def WEB_BOUNCES_INSERT_SQL(
    date_start: str,
    date_end: str,
    team_ids: list[int] | None = None,
    timezone: str = "UTC",
    settings: str = "",
    table_name: str = "web_bounces_daily",
    granularity: str = "daily",
    select_only: bool = False,
) -> str:
    filters = get_all_filters(date_start, date_end, timezone, team_ids, granularity, settings)

    query = """
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
        has_gclid,
        has_gad_source_paid_search,
        has_fbclid,
        {mat_metadata_loggedIn_expr},
        {mat_metadata_backend_expr},
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
            any(events__session.has_gclid) AS has_gclid,
            any(events__session.has_gad_source_paid_search) AS has_gad_source_paid_search,
            any(events__session.has_fbclid) AS has_fbclid,
            {mat_metadata_loggedIn_inner_expr},
            {mat_metadata_backend_inner_expr},
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
                notEmpty(argMinMerge(raw_sessions.initial_gclid)) AND argMinMerge(raw_sessions.initial_gclid) != 'null' AS has_gclid,
                argMinMerge(raw_sessions.initial_gad_source) = '1' AS has_gad_source_paid_search,
                notEmpty(argMinMerge(raw_sessions.initial_fbclid)) AND argMinMerge(raw_sessions.initial_fbclid) != 'null' AS has_fbclid,
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
                AND fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) >= {session_start_filter}
                AND fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000)) <= {session_end_filter}
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
            AND toTimeZone(e.timestamp, '{timezone}') >= {event_start_filter}
            AND toTimeZone(e.timestamp, '{timezone}') < {event_end_filter}
        GROUP BY
            session_id,
            team_id
    )
    WHERE
        period_bucket >= {target_period_start}
        AND period_bucket < {target_period_end}
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
        viewport_height,
        has_gclid,
        has_gad_source_paid_search,
        has_fbclid{mat_custom_fields_outer_group_by_placeholder}
    {settings_clause}
    """

    formatted_query = query.format(**filters)

    if select_only:
        return formatted_query
    else:
        columns = get_web_bounces_insert_columns()
        column_list = ",\n    ".join(columns)
        return f"INSERT INTO {table_name}\n(\n    {column_list}\n)\n{formatted_query}"


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
    CREATE OR REPLACE VIEW {table_prefix}_combined AS
    SELECT * FROM {table_prefix}_daily WHERE period_bucket < toStartOfDay(now(), 'UTC')
    UNION ALL
    SELECT * FROM {table_prefix}_hourly WHERE period_bucket >= toStartOfDay(now(), 'UTC')
    """


def WEB_STATS_COMBINED_VIEW_SQL():
    return create_combined_view_sql("web_stats")


def WEB_BOUNCES_COMBINED_VIEW_SQL():
    return create_combined_view_sql("web_bounces")

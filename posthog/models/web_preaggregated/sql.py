from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, ReplicationScheme

CLICKHOUSE_CLUSTER = settings.CLICKHOUSE_CLUSTER
CLICKHOUSE_DATABASE = settings.CLICKHOUSE_DATABASE


def TABLE_TEMPLATE(table_name, columns, order_by, on_cluster=True):
    engine = AggregatingMergeTree(table_name, replication_scheme=ReplicationScheme.REPLICATED)
    on_cluster_clause = f"ON CLUSTER '{CLICKHOUSE_CLUSTER}'" if on_cluster else ""
    return f"""
    CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
    (
        day_bucket DateTime,
        team_id UInt64,
        host String,
        device_type String,
        {columns}
    ) ENGINE = {engine}
    PARTITION BY toYYYYMM(day_bucket)
    ORDER BY {order_by}
    """


def DISTRIBUTED_TABLE_TEMPLATE(dist_table_name, base_table_name, columns):
    return f"""
    CREATE TABLE IF NOT EXISTS {dist_table_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}'
    (
        day_bucket DateTime,
        team_id UInt64,
        host String,
        device_type String,
        {columns}
    ) ENGINE = Distributed('{CLICKHOUSE_CLUSTER}', '{CLICKHOUSE_DATABASE}', {base_table_name}, rand())
    """


# Column definitions
WEB_OVERVIEW_METRICS_COLUMNS = """
    persons_uniq_state AggregateFunction(uniq, UUID),
    sessions_uniq_state AggregateFunction(uniq, String),
    pageviews_count_state AggregateFunction(sum, UInt64),
    total_session_duration_state AggregateFunction(sum, Int64),
    total_bounces_state AggregateFunction(sum, UInt64)
"""

WEB_STATS_COLUMNS = """
    browser String,
    os String,
    viewport String,
    referring_domain String,
    utm_source String,
    utm_medium String,
    utm_campaign String,
    utm_term String,
    utm_content String,
    country String,
    persons_uniq_state AggregateFunction(uniq, UUID),
    sessions_uniq_state AggregateFunction(uniq, String),
    pageviews_count_state AggregateFunction(sum, UInt64),
"""

WEB_OVERVIEW_ORDER_BY = "(team_id, day_bucket, host, device_type)"
WEB_STATS_ORDER_BY = "(team_id, day_bucket, host, device_type, os, browser, viewport, referring_domain, utm_source, utm_campaign, utm_medium, country)"

WEB_BOUNCES_COLUMNS = """
    entry_path String,
    persons_uniq_state AggregateFunction(uniq, UUID),
    sessions_uniq_state AggregateFunction(uniq, String),
    pageviews_count_state AggregateFunction(sum, UInt64),
    bounces_count_state AggregateFunction(sum, UInt64)
"""

WEB_BOUNCES_ORDER_BY = "(team_id, day_bucket, host, device_type, entry_path)"

WEB_PATHS_COLUMNS = """
    pathname String,
    persons_uniq_state AggregateFunction(uniq, UUID),
    sessions_uniq_state AggregateFunction(uniq, String),
    pageviews_count_state AggregateFunction(sum, UInt64)
"""

WEB_PATHS_ORDER_BY = "(team_id, day_bucket, host, device_type, pathname)"


def create_table_pair(base_table_name, columns, order_by, on_cluster=True):
    """Create both a local and distributed table with the same schema"""
    base_sql = TABLE_TEMPLATE(base_table_name, columns, order_by, on_cluster)
    dist_sql = DISTRIBUTED_TABLE_TEMPLATE(f"{base_table_name}_distributed", base_table_name, columns)
    return base_sql, dist_sql


def WEB_OVERVIEW_METRICS_DAILY_SQL(table_name="web_overview_metrics_daily", on_cluster=True):
    return TABLE_TEMPLATE(table_name, WEB_OVERVIEW_METRICS_COLUMNS, WEB_OVERVIEW_ORDER_BY, on_cluster)


def DISTRIBUTED_WEB_OVERVIEW_METRICS_DAILY_SQL():
    return DISTRIBUTED_TABLE_TEMPLATE(
        "web_overview_metrics_daily_distributed", "web_overview_metrics_daily", WEB_OVERVIEW_METRICS_COLUMNS
    )


def WEB_STATS_DAILY_SQL(table_name="web_stats_daily", on_cluster=True):
    return TABLE_TEMPLATE(table_name, WEB_STATS_COLUMNS, WEB_STATS_ORDER_BY, on_cluster)


def DISTRIBUTED_WEB_STATS_DAILY_SQL():
    return DISTRIBUTED_TABLE_TEMPLATE("web_stats_daily_distributed", "web_stats_daily", WEB_STATS_COLUMNS)


def WEB_BOUNCES_DAILY_SQL(table_name="web_bounces_daily", on_cluster=True):
    return TABLE_TEMPLATE(table_name, WEB_BOUNCES_COLUMNS, WEB_BOUNCES_ORDER_BY, on_cluster)


def DISTRIBUTED_WEB_BOUNCES_DAILY_SQL():
    return DISTRIBUTED_TABLE_TEMPLATE("web_bounces_daily_distributed", "web_bounces_daily", WEB_BOUNCES_COLUMNS)


def WEB_PATHS_DAILY_SQL(table_name="web_paths_daily", on_cluster=True):
    return TABLE_TEMPLATE(table_name, WEB_PATHS_COLUMNS, WEB_PATHS_ORDER_BY, on_cluster)


def DISTRIBUTED_WEB_PATHS_DAILY_SQL():
    return DISTRIBUTED_TABLE_TEMPLATE("web_paths_daily_distributed", "web_paths_daily", WEB_PATHS_COLUMNS)


def format_team_ids(team_ids):
    return ", ".join(str(team_id) for team_id in team_ids)


def get_team_filters(team_ids):
    team_ids_str = format_team_ids(team_ids) if team_ids else None
    return {
        "raw_sessions": f"raw_sessions.team_id IN({team_ids_str})" if team_ids else "1=1",
        "person_distinct_id_overrides": f"person_distinct_id_overrides.team_id IN({team_ids_str})"
        if team_ids
        else "1=1",
        "events": f"e.team_id IN({team_ids_str})" if team_ids else "1=1",
    }


# This should be similar and kept in sync with what the web_overview query runner needs at posthog/hogql_queries/web_analytics/web_overview.py
# It is ok if we have some difference in order to make the aggregations work.
def WEB_OVERVIEW_INSERT_SQL(
    date_start, date_end, team_ids=None, timezone="UTC", settings="", table_name="web_overview_daily"
):
    filters = get_team_filters(team_ids)
    team_filter = filters["raw_sessions"]
    person_team_filter = filters["person_distinct_id_overrides"]
    events_team_filter = filters["events"]

    return f"""
    INSERT INTO {table_name}
    SELECT
      toStartOfDay(start_timestamp) AS day_bucket,
      team_id,
      host,
      device_type,
      uniqState(assumeNotNull(session_person_id)) AS persons_uniq_state,
      uniqState(assumeNotNull(session_id)) AS sessions_uniq_state,
      sumState(pageview_count) AS pageviews_count_state,
      sumState(session_duration) AS total_session_duration_state,
      sumState(toUInt64(ifNull(is_bounce, 0))) AS total_bounces_state
    FROM
      (
        SELECT
          any(if(NOT (empty (events__override.distinct_id)), events__override.person_id, events.person_id)) AS session_person_id,
          events__session.session_id AS session_id,
          e.mat_$host AS host,
          e.mat_$device_type AS device_type,
          any(events__session.`$session_duration`) AS session_duration,
          any(events__session.`$is_bounce`) AS is_bounce,
          countIf(e.event IN ('$pageview', '$screen')) AS pageview_count,
          e.team_id AS team_id,
          min(events__session.start_timestamp) AS start_timestamp
        FROM events e
        LEFT JOIN (
          /* Session join logic */
          SELECT
            toString(reinterpretAsUUID(bitOr(bitShiftLeft(raw_sessions.session_id_v7, 64), bitShiftRight(raw_sessions.session_id_v7, 64)))) AS session_id,
            min(toTimeZone(raw_sessions.min_timestamp, '{timezone}')) AS start_timestamp,
            dateDiff('second', min(toTimeZone(raw_sessions.min_timestamp, '{timezone}')), max(toTimeZone(raw_sessions.max_timestamp, '{timezone}'))) AS `$session_duration`,
            /* Bounce calculation logic */
            if(ifNull(equals(uniqUpToMerge(1)(raw_sessions.page_screen_autocapture_uniq_up_to), 0), 0), NULL,
              NOT(or(
                ifNull(greater(uniqUpToMerge(1)(raw_sessions.page_screen_autocapture_uniq_up_to), 1), 0),
                greaterOrEquals(dateDiff('second',
                  min(toTimeZone(raw_sessions.min_timestamp, '{timezone}')),
                  max(toTimeZone(raw_sessions.max_timestamp, '{timezone}'))), 10)
              ))
            ) AS `$is_bounce`,
            raw_sessions.session_id_v7 AS session_id_v7
          FROM raw_sessions
          WHERE {team_filter}
            AND toTimeZone(raw_sessions.min_timestamp, '{timezone}') >= toDateTime('{date_start}', '{timezone}')
            AND toTimeZone(raw_sessions.min_timestamp, '{timezone}') < toDateTime('{date_end}', '{timezone}')
          GROUP BY raw_sessions.session_id_v7
          SETTINGS {settings}
        ) AS events__session ON toUInt128(accurateCastOrNull(e.`$session_id`, 'UUID')) = events__session.session_id_v7
        LEFT OUTER JOIN (
          /* Person ID override logic */
          SELECT
            argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
            person_distinct_id_overrides.distinct_id AS distinct_id
          FROM person_distinct_id_overrides
          WHERE {person_team_filter}
          GROUP BY person_distinct_id_overrides.distinct_id
          HAVING ifNull(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version) = 0, 0)
          SETTINGS {settings}
        ) AS events__override ON e.distinct_id = events__override.distinct_id
        WHERE {events_team_filter}
          AND (e.event = '$pageview' OR e.event = '$screen')
          AND isNotNull(e.`$session_id`)
          AND toTimeZone(e.timestamp, '{timezone}') >= toDateTime('{date_start}', '{timezone}')
          AND toTimeZone(e.timestamp, '{timezone}') < toDateTime('{date_end}', '{timezone}')
        GROUP BY events__session.session_id, e.team_id, host, device_type
        SETTINGS {settings}
      )
    GROUP BY day_bucket, team_id, host, device_type
    SETTINGS {settings}
    """


# This should be similar and kept in sync with what the web_stats query runner needs at posthog/hogql_queries/web_analytics/stats_table.py
# It is ok if we have some difference in order to make the aggregations work.
def WEB_STATS_INSERT_SQL(
    date_start, date_end, team_ids=None, timezone="UTC", settings="", table_name="web_stats_daily"
):
    filters = get_team_filters(team_ids)
    team_filter = filters["raw_sessions"]
    person_team_filter = filters["person_distinct_id_overrides"]
    events_team_filter = filters["events"]

    return f"""
    INSERT INTO {table_name}
    SELECT
        toStartOfDay(start_timestamp) AS day_bucket,
        team_id,
        host,
        device_type,
        browser,
        os,
        viewport,
        referring_domain,
        utm_source,
        utm_medium,
        utm_campaign,
        utm_term,
        utm_content,
        country,
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
            concat(toString(e.mat_$viewport_width), 'x', toString(e.mat_$viewport_height)) AS viewport,
            e.mat_$referring_domain AS referring_domain,
            events__session.entry_utm_source AS utm_source,
            events__session.entry_utm_medium AS utm_medium,
            events__session.entry_utm_campaign AS utm_campaign,
            events__session.entry_utm_term AS utm_term,
            events__session.entry_utm_content AS utm_content,
            e.mat_$geoip_country_name AS country,
            countIf(e.event IN ('$pageview', '$screen')) AS pageview_count,
            e.team_id AS team_id,
            min(events__session.start_timestamp) AS start_timestamp
        FROM events AS e
        LEFT JOIN
        (
            SELECT
                toString(reinterpretAsUUID(bitOr(bitShiftLeft(raw_sessions.session_id_v7, 64), bitShiftRight(raw_sessions.session_id_v7, 64)))) AS session_id,
                min(toTimeZone(raw_sessions.min_timestamp, '{timezone}')) AS start_timestamp,
                argMinMerge(raw_sessions.initial_utm_source) AS entry_utm_source,
                argMinMerge(raw_sessions.initial_utm_medium) AS entry_utm_medium,
                argMinMerge(raw_sessions.initial_utm_campaign) AS entry_utm_campaign,
                argMinMerge(raw_sessions.initial_utm_term) AS entry_utm_term,
                argMinMerge(raw_sessions.initial_utm_content) AS entry_utm_content,
                raw_sessions.session_id_v7 AS session_id_v7
            FROM raw_sessions
            WHERE {team_filter}
                AND toTimeZone(raw_sessions.min_timestamp, '{timezone}') >= toDateTime('{date_start}', '{timezone}')
                AND toTimeZone(raw_sessions.min_timestamp, '{timezone}') < toDateTime('{date_end}', '{timezone}')
            GROUP BY
                raw_sessions.session_id_v7
            SETTINGS {settings}
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
            SETTINGS {settings}
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
            viewport,
            referring_domain,
            utm_source,
            utm_medium,
            utm_campaign,
            utm_term,
            utm_content,
            country
        SETTINGS {settings}
    )
    GROUP BY
        day_bucket,
        team_id,
        host,
        device_type,
        browser,
        os,
        viewport,
        referring_domain,
        utm_source,
        utm_medium,
        utm_campaign,
        utm_term,
        utm_content,
        country
    SETTINGS {settings}
    """


def WEB_BOUNCES_INSERT_SQL(
    date_start, date_end, team_ids=None, timezone="UTC", settings="", table_name="web_bounces_daily"
):
    filters = get_team_filters(team_ids)
    team_filter = filters["raw_sessions"]
    person_team_filter = filters["person_distinct_id_overrides"]
    events_team_filter = filters["events"]

    return f"""
    INSERT INTO {table_name}
    SELECT
        toStartOfDay(start_timestamp) AS day_bucket,
        team_id,
        host,
        device_type,
        entry_path,
        uniqState(assumeNotNull(person_id)) AS persons_uniq_state,
        uniqState(assumeNotNull(session_id)) AS sessions_uniq_state,
        sumState(pageview_count) AS pageviews_count_state,
        sumState(toUInt64(ifNull(is_bounce, 0))) AS bounces_count_state
    FROM
    (
        SELECT
            any(if(NOT empty(events__override.distinct_id), events__override.person_id, events.person_id)) AS person_id,
            countIf(e.event IN ('$pageview', '$screen')) AS pageview_count,
            events__session.entry_path AS entry_path,
            events__session.session_id AS session_id,
            any(events__session.is_bounce) AS is_bounce,
            e.mat_$host AS host,
            e.mat_$device_type AS device_type,
            e.team_id AS team_id,
            min(events__session.start_timestamp) AS start_timestamp
        FROM events AS e
        LEFT JOIN
        (
            SELECT
                path(coalesce(argMinMerge(raw_sessions.entry_url), '')) AS entry_path,
                toString(reinterpretAsUUID(bitOr(bitShiftLeft(raw_sessions.session_id_v7, 64), bitShiftRight(raw_sessions.session_id_v7, 64)))) AS session_id,
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
                AND toTimeZone(raw_sessions.min_timestamp, '{timezone}') >= toDateTime('{date_start}', '{timezone}')
                AND toTimeZone(raw_sessions.min_timestamp, '{timezone}') < toDateTime('{date_end}', '{timezone}')
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
            entry_path,
            team_id,
            host,
            device_type
    )
    GROUP BY
        day_bucket,
        team_id,
        entry_path,
        host,
        device_type
    SETTINGS {settings}
    """


def WEB_PATHS_INSERT_SQL(
    date_start, date_end, team_ids=None, timezone="UTC", settings="", table_name="web_paths_daily"
):
    filters = get_team_filters(team_ids)
    team_filter = filters["raw_sessions"]
    person_team_filter = filters["person_distinct_id_overrides"]
    events_team_filter = filters["events"]

    return f"""
    INSERT INTO {table_name}
    SELECT
        toStartOfDay(timestamp) AS day_bucket,
        team_id,
        host,
        device_type,
        pathname,
        uniqState(assumeNotNull(person_id)) AS persons_uniq_state,
        uniqState(assumeNotNull(session_id)) AS sessions_uniq_state,
        sumState(toUInt64(1)) AS pageviews_count_state
    FROM
    (
        SELECT
            any(if(NOT empty(events__override.distinct_id), events__override.person_id, events.person_id)) AS person_id,
            events__session.session_id AS session_id,
            e.mat_$host AS host,
            e.mat_$device_type AS device_type,
            e.mat_$pathname AS pathname,
            e.team_id AS team_id,
            min(e.timestamp) AS timestamp
        FROM events AS e
        LEFT JOIN
        (
            SELECT
                toString(reinterpretAsUUID(bitOr(bitShiftLeft(raw_sessions.session_id_v7, 64), bitShiftRight(raw_sessions.session_id_v7, 64)))) AS session_id,
                raw_sessions.session_id_v7 AS session_id_v7
            FROM raw_sessions
            WHERE {team_filter}
                AND toTimeZone(raw_sessions.min_timestamp, '{timezone}') >= toDateTime('{date_start}', '{timezone}')
                AND toTimeZone(raw_sessions.min_timestamp, '{timezone}') < toDateTime('{date_end}', '{timezone}')
            GROUP BY raw_sessions.session_id_v7
            SETTINGS {settings}
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
            SETTINGS {settings}
        ) AS events__override ON e.distinct_id = events__override.distinct_id
        WHERE {events_team_filter}
            AND ((e.event = '$pageview') OR (e.event = '$screen'))
            AND (e.`$session_id` IS NOT NULL)
            AND toTimeZone(e.timestamp, '{timezone}') >= toDateTime('{date_start}', '{timezone}')
            AND toTimeZone(e.timestamp, '{timezone}') < toDateTime('{date_end}', '{timezone}')
        GROUP BY
            session_id,
            team_id,
            host,
            device_type,
            pathname
        SETTINGS {settings}
    )
    GROUP BY
        day_bucket,
        team_id,
        host,
        device_type,
        pathname
    SETTINGS {settings}
    """

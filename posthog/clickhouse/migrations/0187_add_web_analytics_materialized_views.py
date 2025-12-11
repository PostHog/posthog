from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions


def create_bounces_entry_pathname_mv():
    return """
    CREATE MATERIALIZED VIEW IF NOT EXISTS web_bounces_mv_entry_pathname
    REFRESH EVERY 1 HOUR
    ENGINE = AggregatingMergeTree()
    ORDER BY (team_id, period_bucket, entry_pathname, host)
    AS SELECT
        team_id,
        period_bucket,
        entry_pathname,
        host,
        uniqMergeState(persons_uniq_state) AS persons_uniq_state,
        uniqMergeState(sessions_uniq_state) AS sessions_uniq_state,
        sumMergeState(pageviews_count_state) AS pageviews_count_state,
        sumMergeState(bounces_count_state) AS bounces_count_state,
        sumMergeState(total_session_duration_state) AS total_session_duration_state,
        sumMergeState(total_session_count_state) AS total_session_count_state
    FROM web_pre_aggregated_bounces
    GROUP BY team_id, period_bucket, entry_pathname, host
    """


def create_bounces_overview_mv():
    return """
    CREATE MATERIALIZED VIEW IF NOT EXISTS web_bounces_mv_overview
    REFRESH EVERY 1 HOUR
    ENGINE = AggregatingMergeTree()
    ORDER BY (team_id, period_bucket)
    AS SELECT
        team_id,
        period_bucket,
        uniqMergeState(persons_uniq_state) AS persons_uniq_state,
        uniqMergeState(sessions_uniq_state) AS sessions_uniq_state,
        sumMergeState(pageviews_count_state) AS pageviews_count_state,
        sumMergeState(bounces_count_state) AS bounces_count_state,
        sumMergeState(total_session_duration_state) AS total_session_duration_state,
        sumMergeState(total_session_count_state) AS total_session_count_state
    FROM web_pre_aggregated_bounces
    GROUP BY team_id, period_bucket
    """


def create_stats_pathname_mv():
    return """
    CREATE MATERIALIZED VIEW IF NOT EXISTS web_stats_mv_pathname
    REFRESH EVERY 1 HOUR
    ENGINE = AggregatingMergeTree()
    ORDER BY (team_id, period_bucket, pathname, host)
    AS SELECT
        team_id,
        period_bucket,
        pathname,
        host,
        uniqMergeState(persons_uniq_state) AS persons_uniq_state,
        uniqMergeState(sessions_uniq_state) AS sessions_uniq_state,
        sumMergeState(pageviews_count_state) AS pageviews_count_state
    FROM web_pre_aggregated_stats
    GROUP BY team_id, period_bucket, pathname, host
    """


def create_stats_end_pathname_mv():
    return """
    CREATE MATERIALIZED VIEW IF NOT EXISTS web_stats_mv_end_pathname
    REFRESH EVERY 1 HOUR
    ENGINE = AggregatingMergeTree()
    ORDER BY (team_id, period_bucket, end_pathname, host)
    AS SELECT
        team_id,
        period_bucket,
        end_pathname,
        host,
        uniqMergeState(persons_uniq_state) AS persons_uniq_state,
        uniqMergeState(sessions_uniq_state) AS sessions_uniq_state,
        sumMergeState(pageviews_count_state) AS pageviews_count_state
    FROM web_pre_aggregated_stats
    GROUP BY team_id, period_bucket, end_pathname, host
    """


def create_stats_device_type_mv():
    return """
    CREATE MATERIALIZED VIEW IF NOT EXISTS web_stats_mv_device_type
    REFRESH EVERY 1 HOUR
    ENGINE = AggregatingMergeTree()
    ORDER BY (team_id, period_bucket, device_type, host)
    AS SELECT
        team_id,
        period_bucket,
        device_type,
        host,
        uniqMergeState(persons_uniq_state) AS persons_uniq_state,
        uniqMergeState(sessions_uniq_state) AS sessions_uniq_state,
        sumMergeState(pageviews_count_state) AS pageviews_count_state
    FROM web_pre_aggregated_stats
    GROUP BY team_id, period_bucket, device_type, host
    """


def create_stats_country_mv():
    return """
    CREATE MATERIALIZED VIEW IF NOT EXISTS web_stats_mv_country
    REFRESH EVERY 1 HOUR
    ENGINE = AggregatingMergeTree()
    ORDER BY (team_id, period_bucket, country_code, host)
    AS SELECT
        team_id,
        period_bucket,
        country_code,
        host,
        uniqMergeState(persons_uniq_state) AS persons_uniq_state,
        uniqMergeState(sessions_uniq_state) AS sessions_uniq_state,
        sumMergeState(pageviews_count_state) AS pageviews_count_state
    FROM web_pre_aggregated_stats
    GROUP BY team_id, period_bucket, country_code, host
    """


def drop_view(view_name: str):
    return f"DROP VIEW IF EXISTS {view_name}"


operations = [
    # Create bounces materialized views
    run_sql_with_exceptions(
        create_bounces_entry_pathname_mv(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        rollback=drop_view("web_bounces_mv_entry_pathname"),
    ),
    run_sql_with_exceptions(
        create_bounces_overview_mv(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        rollback=drop_view("web_bounces_mv_overview"),
    ),
    # Create stats materialized views
    run_sql_with_exceptions(
        create_stats_pathname_mv(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        rollback=drop_view("web_stats_mv_pathname"),
    ),
    run_sql_with_exceptions(
        create_stats_end_pathname_mv(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        rollback=drop_view("web_stats_mv_end_pathname"),
    ),
    run_sql_with_exceptions(
        create_stats_device_type_mv(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        rollback=drop_view("web_stats_mv_device_type"),
    ),
    run_sql_with_exceptions(
        create_stats_country_mv(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        rollback=drop_view("web_stats_mv_country"),
    ),
]

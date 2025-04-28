from typing import Literal
from django.conf import settings

CLICKHOUSE_CLUSTER = settings.CLICKHOUSE_CLUSTER
CLICKHOUSE_DATABASE = settings.CLICKHOUSE_DATABASE


def TABLE_TEMPLATE(table_name, columns, order_by, on_cluster=True):
    on_cluster_clause = f"ON CLUSTER '{CLICKHOUSE_CLUSTER}'" if on_cluster else ""
    return f"""
    CREATE OR REPLACE TABLE {table_name} {on_cluster_clause}
    (
        day_bucket DateTime,
        team_id UInt64,
        host String,
        device_type String,
        {columns}
    ) ENGINE = AggregatingMergeTree()
    PARTITION BY toYYYYMM(day_bucket)
    ORDER BY {order_by}
    """


def DISTRIBUTED_TABLE_TEMPLATE(dist_table_name, base_table_name, columns):
    return f"""
    CREATE OR REPLACE TABLE {dist_table_name} ON CLUSTER '{CLICKHOUSE_CLUSTER}'
    (
        day_bucket DateTime,
        team_id UInt64,
        host String,
        device_type String,
        {columns}
    ) ENGINE = Distributed('{CLICKHOUSE_CLUSTER}', '{CLICKHOUSE_DATABASE}', {base_table_name}, rand())
    """


# Overview metrics table
def WEB_OVERVIEW_METRICS_DAILY_SQL(on_cluster=True):
    columns = """
        persons_uniq_state AggregateFunction(uniq, UUID),
        sessions_uniq_state AggregateFunction(uniq, String),
        pageviews_count_state AggregateFunction(sum, UInt64),
        total_session_duration_state AggregateFunction(sum, Int64),
        total_bounces_state AggregateFunction(sum, UInt64)
    """
    order_by = "(team_id, day_bucket, host, device_type)"
    return TABLE_TEMPLATE("web_overview_metrics_daily", columns, order_by, on_cluster)


def DISTRIBUTED_WEB_OVERVIEW_METRICS_DAILY_SQL():
    columns = """
        persons_uniq_state AggregateFunction(uniq, UUID),
        sessions_uniq_state AggregateFunction(uniq, String),
        pageviews_count_state AggregateFunction(sum, UInt64),
        total_session_duration_state AggregateFunction(sum, Int64),
        total_bounces_state AggregateFunction(sum, UInt64)
    """
    return DISTRIBUTED_TABLE_TEMPLATE("web_overview_metrics_daily_distributed", "web_overview_metrics_daily", columns)


# Web stats table
def WEB_STATS_DAILY_SQL(on_cluster=True):
    columns = """
        persons_uniq_state AggregateFunction(uniq, UUID),
        sessions_uniq_state AggregateFunction(uniq, String),
        pageviews_count_state AggregateFunction(sum, UInt64),
        browser String, 
        os String,
        viewport String,
        referring_domain String,
        utm_source String,
        utm_campaign String,
        utm_medium String,
        utm_term String,
        utm_content String,
        country String
    """
    order_by = "(team_id, day_bucket, host, device_type, os, browser, viewport, referring_domain, utm_source, utm_campaign, utm_medium, country)"
    return TABLE_TEMPLATE("web_stats_daily", columns, order_by, on_cluster)


def DISTRIBUTED_WEB_STATS_DAILY_SQL():
    columns = """
        persons_uniq_state AggregateFunction(uniq, UUID),
        sessions_uniq_state AggregateFunction(uniq, String),
        pageviews_count_state AggregateFunction(sum, UInt64),
        browser String, 
        os String,
        viewport String,
        referring_domain String,
        utm_source String,
        utm_campaign String,
        utm_medium String,
        utm_term String,
        utm_content String,
        country String
    """
    return DISTRIBUTED_TABLE_TEMPLATE("web_stats_daily_distributed", "web_stats_daily", columns)

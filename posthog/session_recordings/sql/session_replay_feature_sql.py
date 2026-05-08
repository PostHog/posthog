from django.conf import settings

from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_SESSION_REPLAY_FEATURES,
    CONSUMER_GROUP_SESSION_REPLAY_FEATURES_WS,
    kafka_engine,
)
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_FEATURES

MAX_UNIQ_SET_SIZE = 2000


def SESSION_REPLAY_FEATURES_DATA_TABLE():
    return "sharded_session_replay_features"


KAFKA_SESSION_REPLAY_FEATURES_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    batch_id VARCHAR,
    first_timestamp DateTime64(6, 'UTC'),
    last_timestamp DateTime64(6, 'UTC'),
    event_count Int64,
    mouse_position_count Int64,
    mouse_sum_x Float64,
    mouse_sum_x_squared Float64,
    mouse_sum_y Float64,
    mouse_sum_y_squared Float64,
    mouse_distance_traveled Float64,
    mouse_direction_change_count Int64,
    mouse_velocity_sum Float64,
    mouse_velocity_sum_of_squares Float64,
    mouse_velocity_count Int64,
    scroll_event_count Int64,
    total_scroll_magnitude Float64,
    scroll_direction_reversal_count Int64,
    rapid_scroll_reversal_count Int64,
    scroll_to_top_count Int64,
    click_count Int64,
    keypress_count Int64,
    mouse_activity_count Int64,
    rage_click_count Int64,
    dead_click_count Int64,
    backspace_count Int64,
    inter_action_gap_count Int64,
    inter_action_gap_sum_ms Float64,
    inter_action_gap_sum_of_squares_ms Float64,
    max_idle_gap_ms Float64,
    long_idle_gap_count Int64,
    quick_back_count Int64,
    page_visit_count Int64,
    visited_urls Array(String),
    login_path_visit_count Int64,
    signup_path_visit_count Int64,
    checkout_path_visit_count Int64,
    cart_path_visit_count Int64,
    billing_path_visit_count Int64,
    settings_path_visit_count Int64,
    account_path_visit_count Int64,
    error_path_visit_count Int64,
    not_found_path_visit_count Int64,
    admin_path_visit_count Int64,
    dashboard_path_visit_count Int64,
    onboarding_path_visit_count Int64,
    cancel_path_visit_count Int64,
    refund_path_visit_count Int64,
    console_error_count Int64,
    console_error_after_click_count Int64,
    console_warn_count Int64,
    network_request_count Int64,
    network_failed_request_count Int64,
    network_4xx_count Int64,
    network_5xx_count Int64,
    network_request_duration_sum Float64,
    network_request_duration_sum_of_squares Float64,
    network_request_duration_count Int64,
    mutation_count Int64,
    viewport_resize_count Int64,
    touch_event_count Int64,
    max_scroll_y Float64,
    click_target_ids Array(Int64),
    form_field_ids Array(Int64),
    text_selection_count Int64,
    selection_copy_count Int64,
    is_deleted UInt8
) ENGINE = {engine}
"""

SESSION_REPLAY_FEATURES_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    min_first_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_last_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    event_count SimpleAggregateFunction(sum, Int64),
    mouse_position_count SimpleAggregateFunction(sum, Int64),
    mouse_sum_x SimpleAggregateFunction(sum, Float64),
    mouse_sum_x_squared SimpleAggregateFunction(sum, Float64),
    mouse_sum_y SimpleAggregateFunction(sum, Float64),
    mouse_sum_y_squared SimpleAggregateFunction(sum, Float64),
    mouse_distance_traveled SimpleAggregateFunction(sum, Float64),
    mouse_direction_change_count SimpleAggregateFunction(sum, Int64),
    mouse_velocity_sum SimpleAggregateFunction(sum, Float64),
    mouse_velocity_sum_of_squares SimpleAggregateFunction(sum, Float64),
    mouse_velocity_count SimpleAggregateFunction(sum, Int64),
    scroll_event_count SimpleAggregateFunction(sum, Int64),
    total_scroll_magnitude SimpleAggregateFunction(sum, Float64),
    scroll_direction_reversal_count SimpleAggregateFunction(sum, Int64),
    rapid_scroll_reversal_count SimpleAggregateFunction(sum, Int64),
    scroll_to_top_count SimpleAggregateFunction(sum, Int64),
    click_count SimpleAggregateFunction(sum, Int64),
    keypress_count SimpleAggregateFunction(sum, Int64),
    mouse_activity_count SimpleAggregateFunction(sum, Int64),
    rage_click_count SimpleAggregateFunction(sum, Int64),
    dead_click_count SimpleAggregateFunction(sum, Int64),
    backspace_count SimpleAggregateFunction(sum, Int64),
    inter_action_gap_count SimpleAggregateFunction(sum, Int64),
    inter_action_gap_sum_ms SimpleAggregateFunction(sum, Float64),
    inter_action_gap_sum_of_squares_ms SimpleAggregateFunction(sum, Float64),
    max_idle_gap_ms SimpleAggregateFunction(max, Float64),
    long_idle_gap_count SimpleAggregateFunction(sum, Int64),
    quick_back_count SimpleAggregateFunction(sum, Int64),
    page_visit_count SimpleAggregateFunction(sum, Int64),
    unique_url_count AggregateFunction(uniqUpTo({max_uniq_set_size}), String),
    login_path_visit_count SimpleAggregateFunction(sum, Int64),
    signup_path_visit_count SimpleAggregateFunction(sum, Int64),
    checkout_path_visit_count SimpleAggregateFunction(sum, Int64),
    cart_path_visit_count SimpleAggregateFunction(sum, Int64),
    billing_path_visit_count SimpleAggregateFunction(sum, Int64),
    settings_path_visit_count SimpleAggregateFunction(sum, Int64),
    account_path_visit_count SimpleAggregateFunction(sum, Int64),
    error_path_visit_count SimpleAggregateFunction(sum, Int64),
    not_found_path_visit_count SimpleAggregateFunction(sum, Int64),
    admin_path_visit_count SimpleAggregateFunction(sum, Int64),
    dashboard_path_visit_count SimpleAggregateFunction(sum, Int64),
    onboarding_path_visit_count SimpleAggregateFunction(sum, Int64),
    cancel_path_visit_count SimpleAggregateFunction(sum, Int64),
    refund_path_visit_count SimpleAggregateFunction(sum, Int64),
    console_error_count SimpleAggregateFunction(sum, Int64),
    console_error_after_click_count SimpleAggregateFunction(sum, Int64),
    console_warn_count SimpleAggregateFunction(sum, Int64),
    network_request_count SimpleAggregateFunction(sum, Int64),
    network_failed_request_count SimpleAggregateFunction(sum, Int64),
    network_4xx_count SimpleAggregateFunction(sum, Int64),
    network_5xx_count SimpleAggregateFunction(sum, Int64),
    network_request_duration_sum SimpleAggregateFunction(sum, Float64),
    network_request_duration_sum_of_squares SimpleAggregateFunction(sum, Float64),
    network_request_duration_count SimpleAggregateFunction(sum, Int64),
    mutation_count SimpleAggregateFunction(sum, Int64),
    viewport_resize_count SimpleAggregateFunction(sum, Int64),
    touch_event_count SimpleAggregateFunction(sum, Int64),
    max_scroll_y SimpleAggregateFunction(max, Float64),
    unique_click_target_count AggregateFunction(uniqUpTo({max_uniq_set_size}), Int64),
    unique_form_field_count AggregateFunction(uniqUpTo({max_uniq_set_size}), Int64),
    text_selection_count SimpleAggregateFunction(sum, Int64),
    selection_copy_count SimpleAggregateFunction(sum, Int64),
    is_deleted SimpleAggregateFunction(max, UInt8) DEFAULT 0
) ENGINE = {engine}
"""


def SESSION_REPLAY_FEATURES_DATA_TABLE_ENGINE():
    return AggregatingMergeTree("session_replay_features", replication_scheme=ReplicationScheme.SHARDED)


def SESSION_REPLAY_FEATURES_TABLE_SQL(on_cluster=True):
    return (
        SESSION_REPLAY_FEATURES_TABLE_BASE_SQL
        + """
    PARTITION BY toYYYYMM(min_first_timestamp)
    ORDER BY (team_id, session_id)
SETTINGS index_granularity=512
"""
    ).format(
        table_name=SESSION_REPLAY_FEATURES_DATA_TABLE(),
        max_uniq_set_size=MAX_UNIQ_SET_SIZE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=SESSION_REPLAY_FEATURES_DATA_TABLE_ENGINE(),
    )


def KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL(on_cluster=True):
    return KAFKA_SESSION_REPLAY_FEATURES_TABLE_BASE_SQL.format(
        table_name="kafka_session_replay_features",
        max_uniq_set_size=MAX_UNIQ_SET_SIZE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(
            topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_FEATURES,
            group=CONSUMER_GROUP_SESSION_REPLAY_FEATURES,
        ),
    )


_SESSION_REPLAY_FEATURES_MV_SELECT_SQL_TEMPLATE = """SELECT
session_id,
team_id,
any(distinct_id) as distinct_id,
min(first_timestamp) AS min_first_timestamp,
max(last_timestamp) AS max_last_timestamp,
sum(event_count) as event_count,
sum(mouse_position_count) as mouse_position_count,
sum(mouse_sum_x) as mouse_sum_x,
sum(mouse_sum_x_squared) as mouse_sum_x_squared,
sum(mouse_sum_y) as mouse_sum_y,
sum(mouse_sum_y_squared) as mouse_sum_y_squared,
sum(mouse_distance_traveled) as mouse_distance_traveled,
sum(mouse_direction_change_count) as mouse_direction_change_count,
sum(mouse_velocity_sum) as mouse_velocity_sum,
sum(mouse_velocity_sum_of_squares) as mouse_velocity_sum_of_squares,
sum(mouse_velocity_count) as mouse_velocity_count,
sum(scroll_event_count) as scroll_event_count,
sum(total_scroll_magnitude) as total_scroll_magnitude,
sum(scroll_direction_reversal_count) as scroll_direction_reversal_count,
sum(rapid_scroll_reversal_count) as rapid_scroll_reversal_count,
sum(scroll_to_top_count) as scroll_to_top_count,
sum(click_count) as click_count,
sum(keypress_count) as keypress_count,
sum(mouse_activity_count) as mouse_activity_count,
sum(rage_click_count) as rage_click_count,
sum(dead_click_count) as dead_click_count,
sum(backspace_count) as backspace_count,
sum(inter_action_gap_count) as inter_action_gap_count,
sum(inter_action_gap_sum_ms) as inter_action_gap_sum_ms,
sum(inter_action_gap_sum_of_squares_ms) as inter_action_gap_sum_of_squares_ms,
max(max_idle_gap_ms) as max_idle_gap_ms,
sum(long_idle_gap_count) as long_idle_gap_count,
sum(quick_back_count) as quick_back_count,
sum(page_visit_count) as page_visit_count,
uniqUpToArrayState({max_uniq_set_size})(visited_urls) as unique_url_count,
sum(login_path_visit_count) as login_path_visit_count,
sum(signup_path_visit_count) as signup_path_visit_count,
sum(checkout_path_visit_count) as checkout_path_visit_count,
sum(cart_path_visit_count) as cart_path_visit_count,
sum(billing_path_visit_count) as billing_path_visit_count,
sum(settings_path_visit_count) as settings_path_visit_count,
sum(account_path_visit_count) as account_path_visit_count,
sum(error_path_visit_count) as error_path_visit_count,
sum(not_found_path_visit_count) as not_found_path_visit_count,
sum(admin_path_visit_count) as admin_path_visit_count,
sum(dashboard_path_visit_count) as dashboard_path_visit_count,
sum(onboarding_path_visit_count) as onboarding_path_visit_count,
sum(cancel_path_visit_count) as cancel_path_visit_count,
sum(refund_path_visit_count) as refund_path_visit_count,
sum(console_error_count) as console_error_count,
sum(console_error_after_click_count) as console_error_after_click_count,
sum(console_warn_count) as console_warn_count,
sum(network_request_count) as network_request_count,
sum(network_failed_request_count) as network_failed_request_count,
sum(network_4xx_count) as network_4xx_count,
sum(network_5xx_count) as network_5xx_count,
sum(network_request_duration_sum) as network_request_duration_sum,
sum(network_request_duration_sum_of_squares) as network_request_duration_sum_of_squares,
sum(network_request_duration_count) as network_request_duration_count,
sum(mutation_count) as mutation_count,
sum(viewport_resize_count) as viewport_resize_count,
sum(touch_event_count) as touch_event_count,
max(max_scroll_y) as max_scroll_y,
uniqUpToArrayState({max_uniq_set_size})(click_target_ids) as unique_click_target_count,
uniqUpToArrayState({max_uniq_set_size})(form_field_ids) as unique_form_field_count,
sum(text_selection_count) as text_selection_count,
sum(selection_copy_count) as selection_copy_count,
max(is_deleted) as is_deleted"""

SESSION_REPLAY_FEATURES_MV_SELECT_SQL = _SESSION_REPLAY_FEATURES_MV_SELECT_SQL_TEMPLATE.format(
    max_uniq_set_size=MAX_UNIQ_SET_SIZE
)


def SESSION_REPLAY_FEATURES_TABLE_MV_SQL(on_cluster=True):
    database = settings.CLICKHOUSE_DATABASE
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS session_replay_features_mv {ON_CLUSTER_CLAUSE(on_cluster)}
TO {database}.writable_session_replay_features
AS {SESSION_REPLAY_FEATURES_MV_SELECT_SQL}
FROM {database}.kafka_session_replay_features
GROUP BY session_id, team_id
"""


def WRITABLE_SESSION_REPLAY_FEATURES_TABLE_SQL(on_cluster=False):
    return SESSION_REPLAY_FEATURES_TABLE_BASE_SQL.format(
        table_name="writable_session_replay_features",
        max_uniq_set_size=MAX_UNIQ_SET_SIZE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=SESSION_REPLAY_FEATURES_DATA_TABLE(),
            sharding_key="sipHash64(session_id)",
        ),
    )


def DISTRIBUTED_SESSION_REPLAY_FEATURES_TABLE_SQL(on_cluster=False):
    return SESSION_REPLAY_FEATURES_TABLE_BASE_SQL.format(
        table_name="session_replay_features",
        max_uniq_set_size=MAX_UNIQ_SET_SIZE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=SESSION_REPLAY_FEATURES_DATA_TABLE(),
            sharding_key="sipHash64(session_id)",
        ),
    )


def DROP_SESSION_REPLAY_FEATURES_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SESSION_REPLAY_FEATURES_DATA_TABLE()}"


def DROP_KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL():
    return "DROP TABLE IF EXISTS kafka_session_replay_features"


def DROP_SESSION_REPLAY_FEATURES_TABLE_MV_SQL():
    return "DROP TABLE IF EXISTS session_replay_features_mv"


def TRUNCATE_SESSION_REPLAY_FEATURES_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SESSION_REPLAY_FEATURES_DATA_TABLE()}"


# WarpStream Kafka engine tables (coexist alongside MSK tables, same target)

KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE = "kafka_session_replay_features_ws"
SESSION_REPLAY_FEATURES_WS_MV = "session_replay_features_ws_mv"

DROP_KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE_SQL = f"DROP TABLE IF EXISTS {KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE}"
DROP_SESSION_REPLAY_FEATURES_WS_MV_SQL = f"DROP TABLE IF EXISTS {SESSION_REPLAY_FEATURES_WS_MV}"


def KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE_SQL(on_cluster=False):
    return KAFKA_SESSION_REPLAY_FEATURES_TABLE_BASE_SQL.format(
        table_name=KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE,
        max_uniq_set_size=MAX_UNIQ_SET_SIZE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(
            topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_FEATURES,
            group=CONSUMER_GROUP_SESSION_REPLAY_FEATURES_WS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_REPLAY_NAMED_COLLECTION,
        ),
    )


def SESSION_REPLAY_FEATURES_WS_MV_SQL(on_cluster=False):
    database = settings.CLICKHOUSE_DATABASE
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {SESSION_REPLAY_FEATURES_WS_MV} {ON_CLUSTER_CLAUSE(on_cluster)}
TO {database}.writable_session_replay_features
AS {SESSION_REPLAY_FEATURES_MV_SELECT_SQL}
FROM {database}.{KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE}
GROUP BY session_id, team_id
"""

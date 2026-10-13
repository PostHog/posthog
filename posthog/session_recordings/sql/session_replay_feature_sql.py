from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_SESSION_REPLAY_FEATURES, kafka_engine
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_FEATURES


def SESSION_REPLAY_FEATURES_DATA_TABLE():
    return "sharded_session_replay_features"


def TRUNCATE_SESSION_REPLAY_FEATURES_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SESSION_REPLAY_FEATURES_DATA_TABLE()}"


# WarpStream Kafka engine tables (coexist alongside MSK tables, same target)

UNIQ_COMBINED_PRECISION = 12

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


def KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL(on_cluster=True):
    return KAFKA_SESSION_REPLAY_FEATURES_TABLE_BASE_SQL.format(
        table_name="kafka_session_replay_features",
        uniq_combined_precision=UNIQ_COMBINED_PRECISION,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(
            topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_FEATURES,
            group=CONSUMER_GROUP_SESSION_REPLAY_FEATURES,
        ),
    )

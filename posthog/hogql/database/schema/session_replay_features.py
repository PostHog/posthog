from posthog.hogql.database.models import (
    DatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)


class SessionReplayFeaturesTable(Table):
    description: str = (
        "Per-session behavioural feature aggregates derived from recordings (mouse, scroll, click, network, "
        "and timing statistics) used for replay scoring and analysis. Join to recordings via `session_id`."
    )
    fields: dict[str, FieldOrTable] = {
        "session_id": StringDatabaseField(
            name="session_id",
            nullable=False,
            description="Recording session identifier; matches `session_replay_events.session_id`.",
        ),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "distinct_id": StringDatabaseField(
            name="distinct_id", nullable=False, description="Identifier of the user/device for the session."
        ),
        "min_first_timestamp": DateTimeDatabaseField(
            name="min_first_timestamp", nullable=False, description="Earliest event timestamp in the session (in UTC)."
        ),
        "max_last_timestamp": DateTimeDatabaseField(
            name="max_last_timestamp", nullable=False, description="Latest event timestamp in the session (in UTC)."
        ),
        "event_count": IntegerDatabaseField(
            name="event_count", nullable=False, description="Number of snapshot events in the session."
        ),
        "mouse_position_count": IntegerDatabaseField(name="mouse_position_count", nullable=False),
        "mouse_sum_x": FloatDatabaseField(name="mouse_sum_x", nullable=False),
        "mouse_sum_x_squared": FloatDatabaseField(name="mouse_sum_x_squared", nullable=False),
        "mouse_sum_y": FloatDatabaseField(name="mouse_sum_y", nullable=False),
        "mouse_sum_y_squared": FloatDatabaseField(name="mouse_sum_y_squared", nullable=False),
        "mouse_distance_traveled": FloatDatabaseField(
            name="mouse_distance_traveled", nullable=False, description="Total cursor travel distance, in pixels."
        ),
        "mouse_direction_change_count": IntegerDatabaseField(name="mouse_direction_change_count", nullable=False),
        "mouse_velocity_sum": FloatDatabaseField(name="mouse_velocity_sum", nullable=False),
        "mouse_velocity_sum_of_squares": FloatDatabaseField(name="mouse_velocity_sum_of_squares", nullable=False),
        "mouse_velocity_count": IntegerDatabaseField(name="mouse_velocity_count", nullable=False),
        "scroll_event_count": IntegerDatabaseField(name="scroll_event_count", nullable=False),
        "total_scroll_magnitude": FloatDatabaseField(name="total_scroll_magnitude", nullable=False),
        "scroll_direction_reversal_count": IntegerDatabaseField(name="scroll_direction_reversal_count", nullable=False),
        "rapid_scroll_reversal_count": IntegerDatabaseField(name="rapid_scroll_reversal_count", nullable=False),
        "click_count": IntegerDatabaseField(name="click_count", nullable=False),
        "keypress_count": IntegerDatabaseField(name="keypress_count", nullable=False),
        "mouse_activity_count": IntegerDatabaseField(name="mouse_activity_count", nullable=False),
        "rage_click_count": IntegerDatabaseField(name="rage_click_count", nullable=False),
        "dead_click_count": IntegerDatabaseField(name="dead_click_count", nullable=False),
        "inter_action_gap_count": IntegerDatabaseField(
            name="inter_action_gap_count",
            nullable=False,
            description="Number of gaps measured between consecutive actions.",
        ),
        "inter_action_gap_sum_ms": FloatDatabaseField(
            name="inter_action_gap_sum_ms", nullable=False, description="Sum of gaps between actions, in milliseconds."
        ),
        "inter_action_gap_sum_of_squares_ms": FloatDatabaseField(
            name="inter_action_gap_sum_of_squares_ms",
            nullable=False,
            description="Sum of squared inter-action gaps (ms²), for computing variance.",
        ),
        "max_idle_gap_ms": FloatDatabaseField(
            name="max_idle_gap_ms", nullable=False, description="Longest gap between actions, in milliseconds."
        ),
        "quick_back_count": IntegerDatabaseField(name="quick_back_count", nullable=False),
        "page_visit_count": IntegerDatabaseField(name="page_visit_count", nullable=False),
        "console_error_count": IntegerDatabaseField(name="console_error_count", nullable=False),
        "console_error_after_click_count": IntegerDatabaseField(name="console_error_after_click_count", nullable=False),
        "network_request_count": IntegerDatabaseField(name="network_request_count", nullable=False),
        "network_failed_request_count": IntegerDatabaseField(name="network_failed_request_count", nullable=False),
        "network_request_duration_sum": FloatDatabaseField(
            name="network_request_duration_sum",
            nullable=False,
            description="Sum of network request durations, in milliseconds.",
        ),
        "network_request_duration_sum_of_squares": FloatDatabaseField(
            name="network_request_duration_sum_of_squares",
            nullable=False,
            description="Sum of squared network request durations (ms²), for computing variance.",
        ),
        "network_request_duration_count": IntegerDatabaseField(
            name="network_request_duration_count",
            nullable=False,
            description="Number of network requests contributing to the duration aggregates.",
        ),
        "max_scroll_y": FloatDatabaseField(
            name="max_scroll_y", nullable=False, description="Furthest vertical scroll position reached, in pixels."
        ),
        "text_selection_count": IntegerDatabaseField(name="text_selection_count", nullable=False),
        "is_deleted": IntegerDatabaseField(
            name="is_deleted", nullable=False, description="Whether the session has been deleted (1) or not (0)."
        ),
        # AggregateFunction(uniqExact, …) state. Exposed as plain DatabaseField so users must wrap with
        # uniqExactMerge to get a count. Anything stricter would prevent the merge call from typechecking.
        "unique_url_count": DatabaseField(
            name="unique_url_count",
            nullable=True,
            description="uniqExact aggregate state for distinct URLs; wrap with uniqExactMerge to get a count.",
        ),
        "unique_click_target_count": DatabaseField(
            name="unique_click_target_count",
            nullable=True,
            description="uniqExact aggregate state for distinct click targets; wrap with uniqExactMerge to get a count.",
        ),
    }

    def to_printed_clickhouse(self, context):
        return "session_replay_features"

    def to_printed_hogql(self):
        return "session_replay_features"

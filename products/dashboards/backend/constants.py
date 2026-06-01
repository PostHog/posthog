# Keep in sync with frontend `BREAKPOINT_COLUMN_COUNTS.sm`.
DASHBOARD_GRID_COLUMN_COUNT = 12

# Cap per-query row count so run-widgets responses stay bounded.
MAX_WIDGET_RESULT_LIMIT = 25

# Default row count for error_tracking_list when config omits limit (matches catalog + OpenAPI).
DEFAULT_ERROR_TRACKING_LIST_WIDGET_LIMIT = 10

# Default row count for session_replay_list when config omits limit (matches catalog + OpenAPI).
DEFAULT_SESSION_REPLAY_LIST_WIDGET_LIMIT = 10

# Cap widgets per batch create / run-widgets request.
MAX_WIDGETS_BATCH_SIZE = 10

# Preset relative ranges only — widgets don't accept arbitrary HogQL date strings.
WIDGET_DATE_FROM_VALUES = frozenset({"-1h", "-3h", "-24h", "-7d", "-14d", "-30d", "-90d"})

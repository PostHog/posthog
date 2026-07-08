# Keep in sync with frontend `BREAKPOINT_COLUMN_COUNTS.sm`.
DASHBOARD_GRID_COLUMN_COUNT = 12

# Hard cap on rows returned per widget query (run_widgets throttles + UI "25+" footer).
MAX_WIDGET_RESULT_LIMIT = 25

# Default when config omits limit — catalog/OpenAPI default, below the hard cap.
DEFAULT_WIDGET_LIST_LIMIT = 10

# Activity events list allows a larger page than other list widgets (lightweight rows).
ACTIVITY_EVENTS_MAX_LIMIT = 50
ACTIVITY_EVENTS_DEFAULT_LIMIT = 25

# Logs list allows the largest page — log rows are cheap and users scan many at once.
LOGS_LIST_MAX_LIMIT = 100
LOGS_LIST_DEFAULT_LIMIT = 50

# Cap widgets per batch create / run-widgets request.
MAX_WIDGETS_BATCH_SIZE = 10

# Upper bound on pinned recordings pulled from a collection to scope a session replay widget. Bounds the
# session_ids IN clause sent to ClickHouse and the Python list we materialize, matching the saved-filter
# cap (MAX_SAVED_FILTER_SESSION_IDS_PER_PLAYLIST). The widget itself only ever shows MAX_WIDGET_RESULT_LIMIT.
MAX_COLLECTION_SESSION_IDS = 1000

# Preset relative ranges only — widgets don't accept arbitrary HogQL date strings.
# Note: `M` is minutes, `m` would be months (see posthog.utils relative-date parsing).
WIDGET_DATE_FROM_VALUES_ORDERED: tuple[str, ...] = (
    "-1M",
    "-30M",
    "-1h",
    "-3h",
    "-24h",
    "-7d",
    "-14d",
    "-30d",
    "-90d",
)

WIDGET_DATE_FROM_LABELS: dict[str, str] = {
    "-1M": "Last minute",
    "-30M": "Last 30 minutes",
    "-1h": "Last hour",
    "-3h": "Last 3 hours",
    "-24h": "Last 24 hours",
    "-7d": "Last 7 days",
    "-14d": "Last 14 days",
    "-30d": "Last 30 days",
    "-90d": "Last 90 days",
}

# Keep in sync with frontend `BREAKPOINT_COLUMN_COUNTS.sm`.
DASHBOARD_GRID_COLUMN_COUNT = 12

# Hard cap on rows returned per widget query (run_widgets throttles + UI "25+" footer).
MAX_WIDGET_RESULT_LIMIT = 25

# Default when config omits limit — catalog/OpenAPI default, below the hard cap.
DEFAULT_WIDGET_LIST_LIMIT = 10

# Cap widgets per batch create / run-widgets request.
MAX_WIDGETS_BATCH_SIZE = 10

# Preset relative ranges only — widgets don't accept arbitrary HogQL date strings.
WIDGET_DATE_FROM_VALUES_ORDERED: tuple[str, ...] = ("-1h", "-3h", "-24h", "-7d", "-14d", "-30d", "-90d")

WIDGET_DATE_FROM_LABELS: dict[str, str] = {
    "-1h": "Last hour",
    "-3h": "Last 3 hours",
    "-24h": "Last 24 hours",
    "-7d": "Last 7 days",
    "-14d": "Last 14 days",
    "-30d": "Last 30 days",
    "-90d": "Last 90 days",
}

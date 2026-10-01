USAGE_REPORT_EVENTS_PREAGG_TABLE = "usage_report_events_preagg"
WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE = f"writable_{USAGE_REPORT_EVENTS_PREAGG_TABLE}"

# Must match the TTL of the table in posthog/clickhouse/schema/catalog/usage_report_events_preagg.
USAGE_REPORT_EVENTS_PREAGG_TTL_DAYS = 14

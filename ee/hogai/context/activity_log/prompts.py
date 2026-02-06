ACTIVITY_LOG_CONTEXT_TEMPLATE = """
## Activity log

Showing {count} entries{scope_filter}{user_filter}.

{entries}
""".strip()

ACTIVITY_LOG_ENTRY_TEMPLATE = """
- **{timestamp}** | {scope} | {activity} | {item_name}{user_attribution}{changes}
""".strip()

ACTIVITY_LOG_NO_RESULTS = "No activity log entries found matching the given filters."

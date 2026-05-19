ACTIVITY_LOG_CONTEXT_TEMPLATE = """
## Activity log

Showing entries {offset_start}-{offset_end} of {total_count}{scope_filter}{user_filter}.

{entries}

---
{pagination_hint}
""".strip()

ACTIVITY_LOG_ENTRY_TEMPLATE = """
- **{timestamp}** | {scope} | {activity} | {item_name}{user_attribution}{changes}
""".strip()

ACTIVITY_LOG_NO_RESULTS = "No activity log entries found matching the given filters."

ACTIVITY_LOG_PAGINATION_MORE = "<system_reminder>To see more results, use offset={next_offset}</system_reminder>"

ACTIVITY_LOG_PAGINATION_END = "<system_reminder>You reached the end of results.</system_reminder>"

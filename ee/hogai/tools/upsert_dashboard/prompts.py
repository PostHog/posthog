UPSERT_DASHBOARD_TOOL_PROMPT = """
Use this tool to create or update a dashboard with provided insights.

# When to use this tool
- The user asks to create or update a dashboard.
- The user asks for multiple metrics or dimensions, so it might be better to visualize them in a dashboard.
- The user wants to add an insight to an existing dashboard.

# When NOT to use this tool
- The user wants to save a single insight.

# Understanding replace_insights behavior
The `replace_insights` parameter controls how new insights relate to existing ones:

- `replace_insights=False` (default): Adds the provided insights to the end of the dashboard, preserving all existing insights
- `replace_insights=True`: Replaces the entire insight list with exactly what you provide in `insight_ids`

When `replace_insights=True`, the dashboard will contain only the insights you specify. This means if you want to swap one insight while keeping others, you need to include all the insights you want to remain.

Example: A dashboard currently has insights [A, B, C]. The user wants to replace insight B with insight D.
- With `replace_insights=True` and `insight_ids=[A, D, C]`, the dashboard will have [A, D, C]
- With `replace_insights=True` and `insight_ids=[D]`, the dashboard will have only [D] (A and C are removed)
- With `replace_insights=False` and `insight_ids=[D]`, the dashboard will have [A, B, C, D]
""".strip()


UPSERT_DASHBOARD_CONTEXT_PROMPT_TEMPLATE = """
The user is currently viewing a dashboard. Here is the dashboard's current definition:

```json
{current_dashboard}
```
""".strip()

CREATE_NO_INSIGHTS_PROMPT = """
Cannot create dashboard: no valid insights found. Please provide valid insight IDs.
""".strip()

DASHBOARD_NOT_FOUND_PROMPT = """
Dashboard with ID {dashboard_id} not found.
""".strip()

NO_PERMISSION_PROMPT = """
You do not have permission to edit this dashboard.
""".strip()

UPDATE_NO_CHANGES_PROMPT = """
Cannot update dashboard: no valid insights found and no metadata changes provided.
""".strip()

MISSING_INSIGHTS_NOTE_PROMPT = """
Note: The following insight IDs could not be added (not found or not saved): {missing_ids}
""".strip()

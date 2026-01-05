UPSERT_DASHBOARD_TOOL_PROMPT = """
Use this tool to create or update a dashboard with provided insights.

# When to use this tool
- The user asks to create or update a dashboard.
- The user asks for multiple metrics or dimensions, so it might be better to visualize them in a dashboard.
- The user wants to add an insight to an existing dashboard.

# When NOT to use this tool
- The user wants to save a single insight.

# CRITICAL: Understanding replace_insights behavior
When updating a dashboard:
- `replace_insights=False` (default): APPENDS the provided insights to the existing insights in the dashboard
- `replace_insights=True`: REMOVES ALL existing insights and ONLY keeps the insights you provide

**IMPORTANT**: To replace a single insight while keeping all others, you MUST:
1. Set `replace_insights=True`
2. Provide ALL insight IDs (both existing ones to keep AND the new/replacement ones)

**Example**: If a dashboard has insights [A, B, C] and the user wants to replace B with D:
- CORRECT: `replace_insights=True`, `insight_ids=[A, D, C]`
- WRONG: `replace_insights=True`, `insight_ids=[D]` (this REMOVES A and C!)
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

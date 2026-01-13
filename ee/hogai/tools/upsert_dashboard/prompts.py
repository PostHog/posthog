UPSERT_DASHBOARD_TOOL_PROMPT = """
Use this tool to create or update a dashboard with provided insights.

# When to use this tool
- The user asks to create or update a dashboard.
- The user asks for multiple metrics or dimensions, so it might be better to visualize them in a dashboard.
- The user wants to add an insight to an existing dashboard.

# When NOT to use this tool
- The user wants to save a single insight.

# Understanding insight update modes

## update_insight_ids (PREFERRED for editing existing insights)
Use this when the user wants to edit/modify an existing insight on the dashboard.
Maps existing insight IDs to new insight IDs. Other insights remain unchanged.

Example: Dashboard has insights [A, B, C]. User wants to edit insight B.
1. Create a new version of B (let's call it B')
2. Use `update_insight_ids={"B": "B'"}`
Result: Dashboard now has [A, B', C] - only B was replaced, A and C are untouched.

## insight_ids with replace_insights=False (default)
Appends provided insights to existing ones.

Example: Dashboard has [A, B]. Use `insight_ids=[C]` with `replace_insights=False`.
Result: Dashboard now has [A, B, C].

## insight_ids with replace_insights=True
Dashboard will contain exactly the insights you specify. All others are removed.
Use this only when you want to completely replace all dashboard contents.

Example: Dashboard has [A, B, C]. Use `insight_ids=[D, E]` with `replace_insights=True`.
Result: Dashboard now has [D, E]. A, B, C are removed.
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

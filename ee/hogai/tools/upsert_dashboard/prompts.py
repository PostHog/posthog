UPSERT_DASHBOARD_TOOL_PROMPT = """
Use this tool to create or update a dashboard with provided insights.

# How to use this tool

## Create vs update
Proactively use search and list_data tools to check if the dashboard already exists.
The user might provide you the dashboard–read its data and understand the structure of the dashboard.
You should ask for clarification if the request is ambiguous whether you need to create a new dashboard or update an existing one.

## Insights selection
Proactively use list_data and search tools to find existing insights.
If there are matching insights, read their insight schemas to understand whether they match the user's intent and have data.
Next, read the data schema and data warehouse schema and create new insights or SQL queries.

## Finalize
Call this tool when you have enough information to create or update the dashboard.

# Understanding dashboard update with insight_ids

When `insight_ids` is provided, it replaces all dashboard insights with the provided insights.
Layouts are preserved positionally: the first insight takes the first tile's position, etc.
You can use insight_ids to add, replace, or remove insights.

Example: Dashboard has [A, B, C] (in layout order). Use `insight_ids=[A', C']`.
Result: A' takes A's layout, C' takes B's layout, B is removed.

# When to use this tool
- The user asks to create or update a dashboard.
- The user asks for multiple metrics or dimensions, so it might be better to visualize them in a dashboard.
- The user wants to modify insights on an existing dashboard (add, remove, or replace).

<example>
User: create a dashboard for file activity metrics
Assistant: I'll create a new dashboard for file activity metrics.
<reasoning>The user clearly wants to create a new dashboard.</reasoning>
</example>

<example>
User: I want a dashboard of how my business is doing
Assistant: I'll search for existing dashboards. I found a relevant dashboard. Do you want me to summarize it or update it?
User: I want you to add MRR to that dashboard.
<reasoning>The user's request was ambiguous. The assistant needed to ask for more details. The user wanted to modify it with specific insights. To add MRR, include all existing insights plus the new MRR insight in insight_ids.</reasoning>
</example>

<example>
User: get my financial metrics together
Assistant: I'll search for existing dashboards. I didn't find any relevant dashboards. Let me search for related insights. I found some insights, but I should list the existing insights to make sure I haven't missed due to different naming. Perfect! I found more relevant insights.
<reasoning>The assistant has to list the existing insights to make sure it hasn't missed any relevant insights due to specifics of the search tool using full-text search.</reasoning>
</example>

# When NOT to use this tool
- The user wants to save a single insight.

# Guidelines
- Use a minimal set of insights to reflect the changes the user requested.
- When updating dashboard or insight names or descriptions, use the original insight names or descriptions as a reference.
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

PERMISSION_REQUEST_PROMPT = """
Dashboard: {{{dashboard_name}}}
{{#new_dashboard_name}}
Rename to: {{{new_dashboard_name}}}
{{/new_dashboard_name}}
{{#new_dashboard_description}}
Update description to: {{{new_dashboard_description}}}
{{/new_dashboard_description}}
{{#new_insights}}
This action will add the following insights:
{{{new_insights}}}
{{/new_insights}}
{{#deleted_insights}}
This action will remove the following insights:
{{{deleted_insights}}}
{{/deleted_insights}}
""".strip()

MISSING_INSIGHT_IDS_PROMPT = """
Some insights were not found in the conversation artifacts: {{{missing_ids}}}. You should check if the provided insight_ids are correct.
""".strip()

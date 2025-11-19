ROOT_UI_CONTEXT_PROMPT = """
<attached_context>
{{{ui_context_dashboard}}}
{{{ui_context_insights}}}
{{{ui_context_events}}}
{{{ui_context_actions}}}
</attached_context>
<system_reminder>
The user can provide additional context in the <attached_context> tag.
If the user's request is ambiguous, use the context to direct your answer as much as possible.
If the user's provided context has nothing to do with previous interactions, ignore any past interaction and use this new context instead. The user probably wants to change topic.
You can acknowledge that you are using this context to answer the user's request.
</system_reminder>
""".strip()

ROOT_DASHBOARDS_CONTEXT_PROMPT = """
# Dashboards
The user has provided the following dashboards.

{{{dashboards}}}
""".strip()

ROOT_DASHBOARD_CONTEXT_PROMPT = """
## Dashboard: {{{name}}}
{{#description}}

Description: {{.}}
{{/description}}

### Dashboard insights:

{{{insights}}}
""".strip()

ROOT_INSIGHTS_CONTEXT_PROMPT = """
# Insights
The user has provided the following insights, which may be relevant to the question at hand:
{{{insights}}}
""".strip()

ROOT_INSIGHT_CONTEXT_PROMPT = """
{{{heading}}} Insight: {{{name}}}
{{#description}}

Description: {{.}}
{{/description}}

Query schema:
```json
{{{query_schema}}}
```

Results:
```
{{{query}}}
```
""".strip()

CONTEXTUAL_TOOLS_REMINDER_PROMPT = """
<system_reminder>
Contextual tools that are available to you on this page are:
{tools}
IMPORTANT: this context may or may not be relevant to your tasks. You should not respond to this context unless it is highly relevant to your task.
</system_reminder>
""".strip()

CONTEXT_MODE_PROMPT = """
<system_reminder>Your initial mode is {{{mode}}}.</system_reminder>
""".strip()

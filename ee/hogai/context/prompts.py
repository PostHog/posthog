ROOT_UI_CONTEXT_PROMPT = """
<attached_context>
{{{context}}}
</attached_context>
<system_reminder>
The user can provide additional context in the <attached_context> tag.
If the user's request is ambiguous, use the context to direct your answer as much as possible.
If the user's provided context has nothing to do with previous interactions, ignore any past interaction and use this new context instead. The user probably wants to change topic.
You can acknowledge that you are using this context to answer the user's request.
</system_reminder>
""".strip()

ROOT_ERROR_TRACKING_ISSUES_CONTEXT_PROMPT = """
# Error Tracking Issues
The user is currently viewing the following error tracking issue(s). When the user refers to "this issue" or asks about an issue, use the ID provided below with any error tracking tools.
{{{issues}}}
""".strip()

ROOT_ERROR_TRACKING_ISSUE_CONTEXT_PROMPT = """
## Issue: {{{name}}}
- ID: {{{id}}}
{{#description}}- Description: {{{description}}}{{/description}}
{{#status}}- Status: {{{status}}}{{/status}}
{{#first_seen}}- First seen: {{{first_seen}}}{{/first_seen}}
{{#occurrences}}- Occurrences: {{{occurrences}}}{{/occurrences}}
{{#users}}- Affected users: {{{users}}}{{/users}}
{{#sessions}}- Affected sessions: {{{sessions}}}{{/sessions}}
{{#assignee}}- Assigned to: {{{assignee}}}{{/assignee}}
""".strip()

ROOT_ERROR_TRACKING_CURRENT_ISSUE_CONTEXT_PROMPT = """
# Current Error Tracking Issue
The user is currently viewing a specific error tracking issue. When the user refers to "this issue" or asks to "summarize/explain this issue", use the JSON definition below as the source of truth.

```json
{{{current_issue}}}
```
""".strip()

ROOT_DASHBOARDS_CONTEXT_PROMPT = """
# Dashboards
The user has provided the following dashboards.

{{{dashboards}}}
""".strip()

ROOT_DASHBOARD_CONTEXT_PROMPT = """
## {{{content}}}
""".strip()

ROOT_INSIGHTS_CONTEXT_PROMPT = """
# Insights
The user has provided the following insights, which may be relevant to the question at hand:
{{{insights}}}
""".strip()

ROOT_INSIGHT_CONTEXT_PROMPT = """
{{{heading}}} {{{insight_prompt}}}
""".strip()

CONTEXTUAL_TOOLS_REMINDER_PROMPT = """
<system_reminder>
Contextual tools that are available to you on this page are:
{tools}
IMPORTANT: this context may or may not be relevant to your tasks. You should not respond to this context unless it is highly relevant to your task.
</system_reminder>
""".strip()

CONTEXT_INITIAL_MODE_PROMPT = "Your initial mode is"
CONTEXT_MODE_SWITCH_PROMPT = "Your mode has been switched to"
CONTEXT_MODE_PROMPT = """
<system_reminder>{{{mode_prompt}}} {{{mode}}}.</system_reminder>
""".strip()

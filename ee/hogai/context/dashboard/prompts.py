DASHBOARD_RESULT_TEMPLATE = """
Dashboard name: {{{dashboard_name}}}
{{#dashboard_id}}
Dashboard ID: {{{dashboard_id}}}
{{/dashboard_id}}
{{#description}}
Description: {{{description}}}
{{/description}}

{{{insights}}}
""".strip()

ROOT_DASHBOARD_CONTEXT_PROMPT = """
## Dashboard: {{{name}}}
{{#description}}

Description: {{.}}
{{/description}}

### Dashboard insights:

{{{insights}}}
""".strip()

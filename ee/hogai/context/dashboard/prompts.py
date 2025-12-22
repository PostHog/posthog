DASHBOARD_RESULT_TEMPLATE = """
Dashboard name: {{{dashboard_name}}}
{{#dashboard_id}}
Dashboard ID: {{{dashboard_id}}}
{{/dashboard_id}}
{{#description}}
Description: {{{description}}}
{{/description}}
{{#insights}}

Dashboard insights:
{{{insights}}}
{{/insights}}
""".strip()

ERROR_TRACKING_FILTERS_RESULT_TEMPLATE = """Error Tracking Issues ({{count}} found{{#limit}}, limited to {{limit}}{{/limit}}):

{{#issues}}
- **{{name}}** (ID: {{id}})
  - Status: {{status}}
  - Occurrences: {{occurrences}}, Users: {{users}}, Sessions: {{sessions}}
  - First seen: {{first_seen}}, Last seen: {{last_seen}}
{{/issues}}
{{^issues}}
No issues found matching the specified filters.
{{/issues}}
"""

ERROR_TRACKING_ISSUE_RESULT_TEMPLATE = """Error Tracking Issue: {{name}}

- **ID**: {{id}}
- **Status**: {{status}}
- **Occurrences**: {{occurrences}}
- **Users affected**: {{users}}
- **Sessions affected**: {{sessions}}
- **First seen**: {{first_seen}}
- **Last seen**: {{last_seen}}
{{#description}}
- **Description**: {{description}}
{{/description}}
{{#assignee}}
- **Assignee**: {{assignee}}
{{/assignee}}
"""

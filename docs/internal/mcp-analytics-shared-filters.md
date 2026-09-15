# MCP Analytics shared filters

Property filters and the test-account setting carry from the dashboard into Tool quality and individual tool reports.
Report links preserve those filters in the URL.
MCP analytics query runners accept event, person, and session property filters. They reject executable HogQL, cohort, and warehouse filters. Project-configured test-account filters still apply when enabled.

Changing a shared filter closes any open failure details and reloads the report.
Select a failure again to see occurrences for the new filters.

Shared controls use one toolbar across Dashboard, Activity, Sessions, Tool quality, and individual tool reports.
Active property filters appear on a separate wrapping row and can be edited or removed individually.
Clear filters removes the property filters and keeps the date range and internal-user setting.
The internal-user menu shows whether those users are included and links to the project filtering settings.
Date controls remain scoped to the report; Activity keeps its feed date control.

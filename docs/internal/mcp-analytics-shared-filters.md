# MCP Analytics shared filters

Property filters and the test-account setting carry from the dashboard into Tool quality and individual tool reports.
Report links preserve those filters in the URL.
MCP analytics query runners accept event, person, and session property filters. They reject executable HogQL, cohort, and warehouse filters. Project-configured test-account filters still apply when enabled.

Changing a shared filter closes any open failure details and reloads the report.
Select a failure again to see occurrences for the new filters.

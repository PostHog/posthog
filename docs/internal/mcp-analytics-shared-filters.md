# MCP Analytics shared filters

Property filters and the test-account setting carry across Dashboard, Tool quality, Sessions, Activity, and individual tool reports.
Report links preserve those filters in the URL.
Date ranges remain specific to each report.

MCP analytics query runners and the Sessions and Activity API endpoints accept event, person, and session property filters.
They reject executable HogQL, cohort, and warehouse filters under the MCP analytics read scope.
Project-configured test-account filters apply when enabled.

Changing a shared filter closes open failure details and reloads the report.
Select a failure again to see occurrences for the new filters.

The shared toolbar sits above each report, with active property filters on a wrapping row.
Clear filters removes property filters but keeps the date range and internal-user setting.
Sessions keeps search and sorting in its list panel.
Activity keeps its feed date control beside the table and uses the shared refresh button.

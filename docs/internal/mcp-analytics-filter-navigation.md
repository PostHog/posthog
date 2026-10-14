# MCP analytics filter navigation

The Dashboard stores its property filters and internal/test-user choice in the URL as `properties` and `filter_test_accounts`.
Tab links, KPI links, and tool-report links carry those parameters so the Dashboard restores the same selection when someone returns.
An absent or invalid `filter_test_accounts` value follows the project's default; `true` and `false` are explicit overrides.

The Dashboard, Tool quality, tool reports, Sessions, and Activity apply the shared property filters and test-account choice.
Their query runners and API endpoints accept event, person, and session property filters and reject executable HogQL, cohort, and warehouse filters under the MCP analytics read scope.

Each report keeps its own date range.
Changing a shared filter closes open failure details and reloads the report.
The shared toolbar wraps active property filters onto a second row when space is limited.

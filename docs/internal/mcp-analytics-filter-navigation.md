# MCP analytics filter navigation

The Dashboard stores its property filters and internal/test-user choice in the URL as `properties` and `filter_test_accounts`.
Tab links, KPI links, and tool-report links carry those parameters so the Dashboard restores the same selection when someone returns.
An absent or invalid `filter_test_accounts` value follows the project's default; `true` and `false` are explicit overrides.

The Tool quality queries accept event, person, and session property filters and the test-account choice.
The Tool quality tab will not apply them until its UI wiring lands.
Tool reports, Sessions, and Activity still need query and UI wiring before their metrics can be described as filtered by these parameters.

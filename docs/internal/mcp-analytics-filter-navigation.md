# MCP analytics filter navigation

The Dashboard stores its property filters and internal/test-user choice in the URL as `properties` and `filter_test_accounts`.
Tab links, KPI links, and tool-report links carry those parameters so the Dashboard restores the same selection when someone returns.
An absent or invalid `filter_test_accounts` value follows the project's default; `true` and `false` are explicit overrides.

This first layer preserves the selection but does not make other tabs use it in their queries.
Tool quality, Sessions, and Activity need their own query and UI wiring before their metrics can be described as filtered by these parameters.

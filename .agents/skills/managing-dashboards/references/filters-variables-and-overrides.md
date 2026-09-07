# Filters, variables, and tile overrides

## Treat filter state as a layered contract

Dashboard query behavior can combine several layers of state.

| Layer                     | Persisted  | Scope                               |
| ------------------------- | ---------- | ----------------------------------- |
| Dashboard filters         | Yes        | Every compatible tile               |
| Dashboard variables       | Yes        | Every compatible tile               |
| Request filter override   | No         | One dashboard read or query request |
| Request variable override | No         | One dashboard read or query request |
| Tile filter override      | Yes        | One insight tile                    |
| Quick filters             | Yes, by ID | Dashboard filter controls           |

Before you change one layer, define its precedence with every other affected layer. Do not infer precedence from the UI.

## Required checks

- Use `normalize_dashboard_filters_properties` for persisted dashboard property filters.
- Keep `persisted_filters` and `persisted_variables` distinct from request-resolved output.
- Shared-token requests ignore request filter and variable overrides.
- Validate quick-filter IDs against the current team. Do not retain a deleted or cross-team ID.
- Preserve tile `filters_overrides` when you duplicate, copy, move, serialize, or create from a template.
- Check tiles that opt out of dashboard filters separately from tiles that add their own filters.
- Apply the same resolved state to dashboard detail, `run_insights`, streaming, export, and the frontend preview.

## Failure cases

| Change               | Check                                                                              |
| -------------------- | ---------------------------------------------------------------------------------- |
| New dashboard filter | Invalid property shape, old filter JSON, and shared rendering                      |
| New variable         | Missing value, invalid value, template substitution, and request-only override     |
| New quick filter     | Missing ID, deleted ID, cross-team ID, and order preservation                      |
| New tile override    | Dashboard filter opt-out, tile-only filter, copy, duplicate, and template behavior |
| New read path        | Persisted output versus request-resolved output and shared-token behavior          |

## Source files

- `products/dashboards/backend/api/dashboard.py`
- `posthog/hogql_queries/apply_dashboard_filters.py`
- `frontend/src/scenes/dashboard/DashboardFilters.tsx`
- `frontend/src/scenes/dashboard/TileFiltersOverride.tsx`
- `frontend/src/scenes/dashboard/dashboardLogic.tsx`

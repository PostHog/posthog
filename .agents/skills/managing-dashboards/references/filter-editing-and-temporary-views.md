# Explicit filter editing and temporary views

Use this reference when a dashboard change affects filter editing, saving, previews, URL filters, or layout editing.

## Filter states

| State                       | Source                                           | Who sees it            | Persisted | Required treatment                                                   |
| --------------------------- | ------------------------------------------------ | ---------------------- | --------- | -------------------------------------------------------------------- |
| Saved filters               | `dashboard.persisted_filters`                    | Every dashboard viewer | Yes       | Render as the dashboard default.                                     |
| Unsaved filter edits        | Local edit state                                 | The current editor     | No        | Show a count and allow preview, discard, or save.                    |
| Temporary URL filters       | `query_filters` URL state                        | The current viewer     | No        | Show a temporary-filter notice and allow clear.                      |
| Temporary URL variables     | `query_variables` URL state                      | The current viewer     | No        | Use distinct variable or value copy. Do not label variables filters. |
| Contextual embedded filters | `setExternalFilters`, currently group dashboards | The current viewer     | No        | Apply to the embedded view. Never count or save as an editor change. |
| Per-tile filter overrides   | `tile.filters_overrides`                         | Every compatible tile  | Yes       | Keep separate from dashboard filter editing.                         |

Do not call normal saved filters temporary. All filters change the displayed data. The temporary state means the current URL selects a different view of the dashboard.

## State transitions

1. A filter edit creates an unsaved local difference from the saved dashboard filters.
2. Preview updates the current dashboard data. Preview does not save the filters.
3. Save filters persists the current filters as the dashboard default.
4. Discard restores the filters saved to the dashboard.
5. Clear temporary filters removes `query_filters` and returns to the saved dashboard view.
6. Clear temporary variables removes `query_variables`. It does not change dashboard filters.
7. An embedded contextual filter constrains its current view. It must not enter the unsaved-filter count or `saveDashboardFilters` payload.

## Layout editing

- Users can enter layout editing while filter edits exist.
- Filter controls remain editable during layout editing.
- Save layout saves only layout changes.
- Save filters saves only filter changes.
- Cancel layout restores layout changes only. It must preserve unsaved filter edits and their preview state.
- Filter actions must remain available during layout editing when unsaved filter edits exist.

## UI requirements

- Use one visible status for one state. Do not show an unsaved-edit status for a URL-only temporary view.
- Make the save target explicit: saving changes the dashboard default for every viewer.
- Make the preview target explicit: preview changes only the current data view.
- The filter-change details must show added, changed, and removed values.
- Render multi-value changes as individual pills.
- Use container queries for narrow dashboard content. At the small filter-bar breakpoint, keep the status visible and move actions into a dropdown.
- Keep temporary-filter details available through an information icon and through click or hover.
- Use filter-specific copy only for `query_filters`. Use separate copy when `query_variables` changes the dashboard view.
- Do not show a temporary URL-filter treatment where the request path ignores URL overrides, such as a shared-token request.

## Entry paths and placements

- A person can open a dashboard with `query_filters` or `query_variables` in a pasted link, browser history entry, or direct URL edit.
- Filter controls write `query_filters` during automatic preview. For large dashboards, Preview writes the same URL state after an explicit action.
- Variable controls write `query_variables`. They use the dashboard variable layer and must not enter filter-save state.
- Group dashboards use `setExternalFilters` for the current group. The embedded dashboard has no dashboard filter editor. Its editor link opens the normal dashboard path without that group context.
- Feature-flag, DataOps, built-in, public, and export placements do not use the normal filter editor. Check each placement before rendering a status or action.
- Tile override dialogs use `tile.filters_overrides`. They are a separate persisted tile action, not a dashboard URL or filter-bar action.

## Required regression checks

- Edit one and multiple filters. Confirm the unsaved count matches the number of changed filter settings.
- Add, change, and remove a property filter, date range, interval, breakdown, and test-account setting.
- Preview edits. Confirm that the dashboard data changes without a persistence request.
- Save filters. Confirm that a reload uses the new saved defaults.
- Discard filter edits. Confirm that saved filters return.
- Open a dashboard with URL filters. Confirm that only the temporary-view treatment appears.
- Clear temporary filters. Confirm that the saved dashboard filters return.
- Open a dashboard with URL variables only. Confirm that the UI identifies temporary variables or values without calling them filters.
- Edit URL filters through browser history or a direct URL edit. Confirm that the resolved dashboard state updates.
- Open a group dashboard. Confirm that its contextual group filter does not make dashboard filters dirty and cannot enter a dashboard filter save.
- Check public, shared, export, feature-flag, DataOps, group, and built-in placements. Confirm that each URL override treatment matches whether that placement applies overrides.
- Edit a tile filter override. Confirm that it does not change dashboard unsaved-filter state.
- Enter and cancel layout editing with unsaved filters. Confirm that filter edits remain.
- Save layout with unsaved filters. Confirm that the layout saves and filter edits remain unsaved.
- Check wide and narrow filter-bar containers. Confirm that direct actions switch to an actions dropdown only at the defined container breakpoint.

## Source files

- `frontend/src/scenes/dashboard/DashboardFilters.tsx`
- `frontend/src/scenes/dashboard/DashboardTemporaryFiltersNotice.tsx`
- `frontend/src/scenes/dashboard/DashboardFilterChangesTooltip.tsx`
- `frontend/src/scenes/dashboard/dashboardFilterChanges.ts`
- `frontend/src/scenes/dashboard/dashboardLogic.tsx`

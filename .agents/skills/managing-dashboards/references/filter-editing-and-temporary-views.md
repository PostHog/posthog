# Explicit filter editing and temporary views

Use this reference when a dashboard change affects filter editing, saving, previews, URL filters, or layout editing.

## Filter states

| State                | Source                        | Who sees it            | Persisted | Required treatment                                |
| -------------------- | ----------------------------- | ---------------------- | --------- | ------------------------------------------------- |
| Saved filters        | `dashboard.persisted_filters` | Every dashboard viewer | Yes       | Render as the dashboard default.                  |
| Unsaved filter edits | Local edit state              | The current editor     | No        | Show a count and allow preview, discard, or save. |
| Temporary filters    | URL filter state              | The current viewer     | No        | Show a temporary-view notice and allow clear.     |

Do not call normal saved filters temporary. All filters change the displayed data. The temporary state means the current URL selects a different view of the dashboard.

## State transitions

1. A filter edit creates an unsaved local difference from the saved dashboard filters.
2. Preview updates the current dashboard data. Preview does not save the filters.
3. Save filters persists the current filters as the dashboard default.
4. Discard restores the filters saved to the dashboard.
5. Clear temporary filters removes URL filter parameters and returns to the saved dashboard view.

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

## Required regression checks

- Edit one and multiple filters. Confirm the unsaved count matches the number of changed filter settings.
- Add, change, and remove a property filter, date range, interval, breakdown, and test-account setting.
- Preview edits. Confirm that the dashboard data changes without a persistence request.
- Save filters. Confirm that a reload uses the new saved defaults.
- Discard filter edits. Confirm that saved filters return.
- Open a dashboard with URL filters. Confirm that only the temporary-view treatment appears.
- Clear temporary filters. Confirm that the saved dashboard filters return.
- Enter and cancel layout editing with unsaved filters. Confirm that filter edits remain.
- Save layout with unsaved filters. Confirm that the layout saves and filter edits remain unsaved.
- Check wide and narrow filter-bar containers. Confirm that direct actions switch to an actions dropdown only at the defined container breakpoint.

## Source files

- `frontend/src/scenes/dashboard/DashboardFilters.tsx`
- `frontend/src/scenes/dashboard/DashboardTemporaryFiltersNotice.tsx`
- `frontend/src/scenes/dashboard/DashboardFilterChangesTooltip.tsx`
- `frontend/src/scenes/dashboard/dashboardFilterChanges.ts`
- `frontend/src/scenes/dashboard/dashboardLogic.tsx`

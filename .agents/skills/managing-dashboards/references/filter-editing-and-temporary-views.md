# Dashboard settings editing and URL overrides

Use this reference when a dashboard change affects filters, SQL variables, previews, URL overrides, saving, or layout editing.

## Settings model

Treat dashboard filters and SQL variables as one editable settings object.

```ts
type DashboardSettings = {
  filters: DashboardFilter
  variables: Record<string, HogQLVariable>
}
```

Use three explicit sources:

| Source               | Contents                                      | Lifetime                             |
| -------------------- | --------------------------------------------- | ------------------------------------ |
| Saved settings       | `persisted_filters` and `persisted_variables` | Persists for every applicable viewer |
| Initial URL override | `query_filters` and `query_variables`         | Applies to the initial view          |
| User draft           | Current filter and variable edits             | Local until save or discard          |

Resolve the current settings in this order:

```text
saved settings
→ initial URL override
→ user draft
```

- Freeze the initial URL override against the URL writes that the filter and variable controls make after the dashboard opens.
- Browser history is the exception. On a `POP`, rebuild the draft from the saved settings and the popped URL. Read `query_filters` and `query_variables` together. A `POP` that carries neither parameter restores the saved settings.
- Do not infer settings state from `dashboardMode`, `hasIntermittentFilters`, or `filterEditModeActive`.
- Do not combine separate temporary-filter and temporary-variable conditions in UI components.
- Keep embedded context and tile overrides outside this configuration.

## Visible states

Derive exactly one visible state from the effective configuration:

| State            | Condition                                                      | Required treatment                                            |
| ---------------- | -------------------------------------------------------------- | ------------------------------------------------------------- |
| `unsavedChanges` | An initial URL override or user draft changes the saved values | Show one count, one change list, and save or discard actions. |
| `saved`          | The current settings equal the saved dashboard settings        | Show no settings status.                                      |

- A filter or SQL-variable edit creates one user draft from the effective configuration.
- Show initial URL overrides through the same unsaved treatment as user edits.
- Do not show a separate temporary treatment.
- The first edit includes the effective override values in the user draft.
- UI code must consume the single derived visible state.
- UI code must not reconstruct state from several selector flags.
- Compare SQL variables by their displayed meaning. Treat absent `isNull` and `isNull: false` as equal.
- Compare a missing saved override with the variable default. Do not report a default selection as a change.
- Preserve explicit SQL `null`. Do not convert it to the string `"null"` in settings or change comparison.

## Actions and transitions

Use explicit actions for each boundary:

- `previewDashboardChanges` updates dashboard data only.
- `saveDashboardChanges` sends one dashboard update with `filters` and `variables`.
- `discardDashboardChanges` clears the user draft and restores the saved configuration.
- `saveLayoutChanges` persists layout changes only.
- `discardLayoutChanges` restores layout changes only.

Save behavior:

1. Persist the final current settings.
2. Include both `filters` and `variables` in one dashboard update.
3. Clear `query_filters` and `query_variables`.
4. Clear the initial URL override and user draft.
5. Confirm that reload shows the saved settings.
6. If automatic preview is disabled, refresh all affected tiles after the save succeeds.

Discard behavior:

1. Clear the user draft.
2. Clear `query_filters` and `query_variables`.
3. Clear the initial URL override.
4. Restore the saved configuration.
5. Never restore the initial temporary view.

- Do not use `saveDashboardFilters` for combined changes.
- Do not use `saveEditModeChanges` for SQL-variable-only changes.
- Do not use `DashboardHeaderOverridesBanner` to clear dashboard configuration overrides.
- For automatic preview, filter and variable controls can update their URL parameters after the draft exists.
- Remove a URL variable when the selected value equals its default.
- Map action payload field names to URL filter field names explicitly. Date actions use camel case. URL filters use snake case.
- Above the automatic-preview threshold, Preview updates data without clearing or saving the draft.
- Any later filter or variable edit invalidates the prior Preview result and returns the Preview action to its idle state.
- Disable the Preview action while its current refresh runs. Do not use a loading spinner for this state.

## Unified change list

Build one `DashboardSettingsChange[]` for filters and SQL variables.

Each displayed row must include:

- A label.
- The old saved or default value.
- The new value.
- A `new`, `changed`, or `removed` status.

Additional requirements:

- The displayed count must equal the number of displayed rows.
- Include every filter and variable change when both types exist.
- Render multi-value changes as individual pills.
- Use generic configuration copy when both types exist.
- Make the save target explicit. Saving changes the dashboard default for every viewer.
- Make the preview target explicit. Preview changes only the current data view.

## Layout independence

- Entering layout mode must preserve the dashboard configuration draft.
- Saving layout must preserve the dashboard configuration draft.
- Discarding layout must preserve the dashboard configuration draft.
- Saving dashboard changes must preserve the layout draft.
- Discarding dashboard changes must preserve the layout draft.
- Filter and variable controls remain editable during layout editing.
- Dashboard settings actions remain available during layout editing.

## Other filter boundaries

- `setExternalFilters` supplies embedded context from the surface that hosts the dashboard. It is not limited to one placement. `DashboardPlacement.Group` and `DashboardPlacement.Builtin` both use it today.
- Search for every caller of `setExternalFilters` before you change its contract.
- Embedded context must not enter the user draft, change count, change list, or save payload.
- `tile.filters_overrides` remains a separate persisted tile action.
- Shared-token requests ignore URL filter and variable overrides.
- Do not claim that URL overrides affect data where the request path ignores them.
- Render save, discard, and Preview only for `DashboardPlacement.Dashboard`.
- Never render these mutation actions for public, embedded, export, built-in, or product-owned placements.
- Other placements can render read-only filters or variables only when their contract supports them.

## UI requirements

- Show SQL-variable controls before the advanced-options ellipsis.
- Keep the status visible at narrow dashboard widths.
- Move actions into a dropdown at the defined narrow container breakpoint.
- Change Preview to Previewing while the dashboard refresh runs.
- Disable Previewing without a spinner.
- Show save and discard labels that describe dashboard settings changes.

## Required regression checks

Use one parameterized Kea logic scenario suite for configuration transitions:

1. Edit one filter. Save it. Confirm that reload shows the saved filter.
2. Edit one SQL variable. Save it. Confirm that reload shows the saved variable.
3. Edit a filter and three SQL variables. Confirm one count, one list, value transitions, and one save.
4. Open a URL override view. Confirm the unsaved state. Edit a filter. Confirm one combined draft.
5. Open a URL override view. Confirm the unsaved state. Edit a SQL variable. Confirm one combined draft.
6. Edit filters and variables from a URL override view. Discard. Confirm that saved state returns.
7. Edit filters and variables from a URL override view. Save. Confirm that the final state persists.
8. Above the automatic-preview threshold, preview filters and variables. Confirm that preview changes data only.
9. Check the complete layout independence matrix for save and discard actions.
10. Save without Preview above the threshold. Confirm that all affected tiles refresh with the saved settings.
11. Edit a SQL variable during or after Preview. Confirm that Preview returns to its idle, enabled state.
12. Select a SQL variable default with absent and false `isNull`. Confirm no change row and no URL override.
13. Set date filters. Confirm that action fields map to the URL and survive reload.

Use DOM tests only for these visible outcomes:

- URL overrides and user edits show the same unsaved pill.
- Count matches visible popover rows.
- Save and discard labels and actions.
- Narrow action dropdown.
- SQL-variable controls appear before the advanced-options ellipsis.
- Save, discard, and Preview never appear outside `DashboardPlacement.Dashboard`.

Do not keep tests that only assert selector flags, action order, a temporary variable, or a dirty filter.

Also check these separate boundaries:

- Embedded contextual filters never enter dashboard configuration changes.
- Tile overrides never enter dashboard configuration changes.
- Shared, public, export, feature-flag, DataOps, group, and built-in placements match their override support.
- Browser history and direct URL edits resolve to the correct effective configuration. Cover a filter-only, a variable-only, and a combined history entry.
- Search for every removed or renamed selector across dashboard items, menus, panels, exports, and tests.
- Run TypeScript after selector changes. Do not stop after the logic tests pass.
- Check the insight-colors modal. Its cancel and save paths must not change the settings draft.

## Manual reproduction

Use one local dashboard with at least two working insight tiles and three SQL variables.

1. Set `dashboard-auto-preview-limit` above the insight-tile count. Edit filters and variables. Confirm immediate preview and one draft.
2. Set the limit at or below the insight-tile count. Edit filters and variables. Confirm that Preview changes data only.
3. Open with both URL override parameters. Confirm the unsaved state. Make one edit. Confirm one combined draft.
4. Save combined changes. Confirm both URL parameters clear. Reload and confirm the saved values.
5. Open with both URL override parameters. Make combined edits. Discard and confirm the original saved values return.
6. Create both dashboard configuration and layout drafts. Run each save and discard action. Confirm that each draft remains independent.

## Storybook coverage

- Keep dashboard stories under `products/dashboards/frontend`, not `scenes`.
- Keep the existing filter variants focused on the visible change list.
- Show up to five different filter changes, including breakdown and date range.
- Do not add variants for URL overrides or layout editing with unsaved filters.
- Do not add a SQL-variable-order variant.
- Do not create a dashboard filter-bar story for embedded context when the embedding surface owns that context.

## Source files

- `frontend/src/scenes/dashboard/DashboardFilters.tsx`
- `frontend/src/scenes/dashboard/DashboardUnsavedChangesIndicator.tsx`
- `frontend/src/scenes/dashboard/dashboardChanges.ts`
- `frontend/src/scenes/dashboard/dashboardLogic.tsx`
- `frontend/src/scenes/dashboard/DashboardItems.tsx`
- `frontend/src/scenes/dashboard/DashboardSceneMenuBar.tsx`
- `frontend/src/scenes/dashboard/DashboardScenePanel.tsx`

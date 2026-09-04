# Dashboard configuration editing and URL overrides

Use this reference when a dashboard change affects filters, SQL variables, previews, URL overrides, saving, or layout editing.

## Configuration model

Treat dashboard filters and SQL variables as one editable configuration.

```ts
type DashboardConfiguration = {
  filters: DashboardFilter
  variables: Record<string, HogQLVariable>
}
```

Use three explicit sources:

| Source               | Contents                                      | Lifetime                             |
| -------------------- | --------------------------------------------- | ------------------------------------ |
| Saved configuration  | `persisted_filters` and `persisted_variables` | Persists for every applicable viewer |
| Initial URL override | `query_filters` and `query_variables`         | Applies to the initial view          |
| User draft           | Current filter and variable edits             | Local until save or discard          |

Resolve the effective configuration in this order:

```text
saved configuration
→ initial URL override
→ user draft
```

- Freeze the initial URL override after the dashboard opens.
- Do not infer configuration state from `dashboardMode`, `hasIntermittentFilters`, or `filterEditModeActive`.
- Do not combine separate temporary-filter and temporary-variable conditions in UI components.
- Keep embedded context and tile overrides outside this configuration.

## Visible states

Derive exactly one visible state from the effective configuration:

| State            | Condition                                                            | Required treatment                                            |
| ---------------- | -------------------------------------------------------------------- | ------------------------------------------------------------- |
| `unsavedChanges` | An initial URL override or user draft changes the saved values       | Show one count, one change list, and save or discard actions. |
| `saved`          | The effective configuration equals the saved dashboard configuration | Show no configuration status.                                 |

- A filter or SQL-variable edit creates one user draft from the effective configuration.
- Show initial URL overrides through the same unsaved treatment as user edits.
- Do not show a separate temporary treatment.
- The first edit includes the effective override values in the user draft.
- UI code must consume the single derived visible state.
- UI code must not reconstruct state from several selector flags.

## Actions and transitions

Use explicit actions for each boundary:

- `previewDashboardChanges` updates dashboard data only.
- `saveDashboardChanges` sends one dashboard update with `filters` and `variables`.
- `discardDashboardChanges` clears the user draft and restores the saved configuration.
- `saveLayoutChanges` persists layout changes only.
- `discardLayoutChanges` restores layout changes only.

Save behavior:

1. Persist the final effective configuration.
2. Include both `filters` and `variables` in one dashboard update.
3. Clear `query_filters` and `query_variables`.
4. Clear the initial URL override and user draft.
5. Confirm that reload shows the saved configuration.

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
- Above the automatic-preview threshold, Preview updates data without clearing or saving the draft.

## Unified change list

Build one `DashboardConfigurationChange[]` for filters and SQL variables.

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
- Dashboard configuration actions remain available during layout editing.

## Other filter boundaries

- `setExternalFilters` supplies embedded context, currently for group dashboards.
- Embedded context must not enter the user draft, change count, change list, or save payload.
- `tile.filters_overrides` remains a separate persisted tile action.
- Shared-token requests ignore URL filter and variable overrides.
- Do not claim that URL overrides affect data where the request path ignores them.
- Public, export, feature-flag, DataOps, group, and built-in placements may use different controls. Check each placement.

## UI requirements

- Show SQL-variable controls before the advanced-options ellipsis.
- Keep the status visible at narrow dashboard widths.
- Move actions into a dropdown at the defined narrow container breakpoint.
- Change Preview to Previewing while the dashboard refresh runs.
- Show save and discard labels that describe dashboard configuration changes.

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

Use DOM tests only for these visible outcomes:

- URL overrides and user edits show the same unsaved pill.
- Count matches visible popover rows.
- Save and discard labels and actions.
- Narrow action dropdown.
- SQL-variable controls appear before the advanced-options ellipsis.

Do not keep tests that only assert selector flags, action order, a temporary variable, or a dirty filter.

Also check these separate boundaries:

- Embedded contextual filters never enter dashboard configuration changes.
- Tile overrides never enter dashboard configuration changes.
- Shared, public, export, feature-flag, DataOps, group, and built-in placements match their override support.
- Browser history and direct URL edits resolve to the correct effective configuration.

## Manual reproduction

Use one local dashboard with at least two working insight tiles and three SQL variables.

1. Set `dashboard-auto-preview-limit` above the insight-tile count. Edit filters and variables. Confirm immediate preview and one draft.
2. Set the limit at or below the insight-tile count. Edit filters and variables. Confirm that Preview changes data only.
3. Open with both URL override parameters. Confirm the unsaved state. Make one edit. Confirm one combined draft.
4. Save combined changes. Confirm both URL parameters clear. Reload and confirm the saved values.
5. Open with both URL override parameters. Make combined edits. Discard and confirm the original saved values return.
6. Create both dashboard configuration and layout drafts. Run each save and discard action. Confirm that each draft remains independent.

## Storybook coverage

- Keep stories for saved configurations, user edits, and URL overrides shown as unsaved changes.
- Do not add a separate temporary treatment story.
- Keep stories for layout editing with an unsaved configuration and for the manual-preview dashboard size.
- Keep a story for the preview loading state above the automatic-preview threshold.
- Keep a story with several SQL variables. Confirm that they appear before the advanced-options ellipsis.
- Do not create a dashboard filter-bar story for embedded context when the embedding surface owns that context.

## Source files

- `frontend/src/scenes/dashboard/DashboardFilters.tsx`
- `frontend/src/scenes/dashboard/DashboardFilterChangesTooltip.tsx`
- `frontend/src/scenes/dashboard/dashboardFilterChanges.ts`
- `frontend/src/scenes/dashboard/dashboardLogic.tsx`

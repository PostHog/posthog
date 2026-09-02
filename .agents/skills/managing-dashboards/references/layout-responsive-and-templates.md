# Layout, responsive behavior, and templates

## Responsive layout

Dashboard layouts are persisted per breakpoint in `DashboardTile.layouts`.

- `sm` is the primary persisted dashboard grid layout.
- Keep backend `DASHBOARD_GRID_COLUMN_COUNT` aligned with frontend `BREAKPOINT_COLUMN_COUNTS.sm`.
- Use `DashboardItems.tsx` and `tileLayouts.ts` as the layout behavior source of truth.
- Check narrow view, wide view, zoom, drag, resize, insert, duplicate, move, copy, and reload.
- Check text, button, insight, error, and widget tiles. Their minimum dimensions differ.
- Preserve existing layout JSON. Older rows can omit a breakpoint or contain a layout that a new rule no longer creates.

## Dense and sparse dashboards

- Empty dashboards need a useful, permission-aware state.
- One tile must not gain unnecessary grid controls or excess whitespace.
- Dense dashboards need stable rendering while tile results refresh.
- Do not make each drag or resize rerender every tile.
- Do not re-layout every tile after each response. Preserve layout references when geometry did not change.
- Test a narrow container. Do not use only a wide desktop Storybook viewport.

## Presentation state

Check these fields when a dashboard change affects chart or tile presentation.

- Dashboard `breakdown_colors` and `data_color_theme` apply across insight tiles.
- Tile `color`, `transparent_background`, and `show_description` are tile-specific state.
- Duplicate, copy, template, serializer, and shared-render paths must preserve or deliberately omit each field.
- Do not treat presentation state as query state. A query refresh must not overwrite a layout or visual preference.

## Template contract

Templates copy a definition. They do not maintain a live relationship with the created dashboard.

Before changing templates, define:

1. Which fields copy to the new dashboard.
2. Which fields require variable substitution.
3. Which references work across projects.
4. Which references are project-specific and need a warning.
5. Which template scope can read, create, edit, delete, or promote the template.
6. Whether the change supports old template JSON.

`DashboardTemplate.Scope` includes team, organization, global, and feature-flag scopes. Non-staff users cannot write every scope or every template field.

## Template checks

- Validate a template with no tiles.
- Validate a template with variables.
- Test copy into the owning project and another permitted project.
- Test project-specific actions, cohorts, and warehouse references.
- Test team, organization, global, and feature-flag scope rules that the change affects.
- Check that template list endpoints do not perform per-template expensive work.

## Verification

```bash
hogli test frontend/src/scenes/dashboard/tileLayouts.test.ts
hogli test frontend/src/scenes/dashboard/insertTileGeometry.test.ts
hogli test frontend/src/scenes/dashboard/editLayoutGesture.test.ts
hogli test products/dashboards/backend/api/test/test_dashboard_templates.py
```

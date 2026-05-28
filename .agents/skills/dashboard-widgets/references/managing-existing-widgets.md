# Managing existing dashboard widgets

Use this when **changing** a shipped widget type — not only when adding a new one.

Reference implementation for patterns: `products/dashboards/frontend/widgets/error_tracking/` (`error_tracking_list`).

## What kind of change?

| Goal | Primary files | Also check |
| ---- | ------------- | ---------- |
| Widget query / `run_widgets` payload | `backend/widgets/<widget_type>.py`, `widget_registry.py` | `test_run_widgets.py`, frontend `Component` types |
| Config fields (filters, limits, sort) | `configSchemas.ts`, `<type>WidgetConfigValidation.ts`, `Edit*WidgetModal.tsx`, backend `validate_*_config` | `utils.ts` API error parser, `hogli build:openapi` if serializers change |
| Tile name / description UX | `Edit*WidgetModal.tsx`, `WidgetSettingsModalSections.tsx` | Mirror `EditErrorTrackingWidgetModal.tsx` field layout |
| Default size when **adding** a tile | `catalog.ts` `defaultLayout.w` / `.h` | `dashboardLogic.addWidgetTiles` (reads catalog defaults) |
| **Min/max resize** on dashboard grid | `catalog.ts` `defaultLayout.minW` / `.minH` | [layout-and-ux.md](layout-and-ux.md) § Tile min/max size — **`tileLayouts.ts`**, `tileLayouts.test.ts` |
| Card header / date range display | `catalog.ts` (`headerLayout`, `headerMeta`, `headerTitle`) | `WidgetCardHeader`, stories |
| Setup / availability gate | `catalog.ts` `availability`, `widgetAvailability.ts` | `WidgetRuntimeAvailabilityGuard` |
| RBAC lock on tile | `widget_registry.py` `required_product_access`, FE `catalog.ts` `productAccess` | `types.ts`, `DashboardWidgetItem.tsx` `userHasWidgetProductAccess` |
| Add-modal preview | `widgets/previews/`, `widgetPreviews.tsx` | Storybook variant stories |
| Storybook / overview fixtures | `WidgetCard/*.stories.tsx`, `widgetOverviewStoryFixtures.ts` | `getWidgetOverviewDemoState` switch per catalog key |

## Config update flow (runtime)

1. User opens ⋯ → **Edit** → `Edit*WidgetModal` validates with Zod → `onSave` / `onSaveMetadata`
2. `dashboardLogic.updateWidgetTileConfig` / `updateWidgetTileMetadata` → PATCH dashboard tile
3. `refreshDashboardWidgets` re-runs `run_widgets` for that tile

Guard saves with `loading` / `disabledReason` on Save — never leave the button clickable mid-mutation.

## Edit modal layout

`WidgetSettingsModalSection` renders a **2-column CSS grid** (`sm:grid-cols-2`).

- Full-width fields (name, description, test-account filter): put `WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS` (`sm:col-span-2`) on the **grid child** — `LemonField.Pure` or a wrapper `<div>` — **not** on the inner `LemonInput` / `LemonTextArea`.
- Half-width fields (date range, sort, limit): omit `col-span-2`; use `fullWidth` on `LemonSelect` where needed.

Copy `EditErrorTrackingWidgetModal.tsx` Tile details + Filters sections when wiring a new edit modal.

## Changing min/max tile size

**Do not** hunt for a single “min height constant” in the widget component — mins are catalog-driven and applied in `tileLayouts.ts`. See [layout-and-ux.md](layout-and-ux.md) § Tile min/max size.

Quick checklist:

1. Set `defaultLayout.minH` / `minW` on the catalog entry in `widget_types/catalog.ts`
2. Add or extend a case in `frontend/src/scenes/dashboard/tileLayouts.test.ts` (`expectedMinH` / `expectedMinW`)
3. Optional: `MinimumSize` story in `<Widget>.stories.tsx` at `minH * 80` px frame height
4. Verify in dashboard **edit mode** by resizing the tile — RGL enforces `minH`/`minW` from `calculateLayouts`, not from persisted tile JSON alone

Changing catalog mins affects **all** tiles of that type on the next layout pass; it does not rewrite stored `h`/`w` in Postgres.

## Verify (updates)

Same as add — run targeted tests for the files you touched:

```bash
hogli test products/dashboards/backend/api/test/test_run_widgets.py   # backend query/config
hogli test frontend/src/scenes/dashboard/tileLayouts.test.ts        # grid mins
hogli test products/dashboards/frontend/widgets/<product>/          # modal + component
```

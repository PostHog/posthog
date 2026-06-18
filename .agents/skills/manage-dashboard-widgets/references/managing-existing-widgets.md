# Managing existing dashboard widgets

**SKILL route:** [SKILL.md §3 Update a shipped type](../SKILL.md#3-update-a-shipped-type) — skip [widget-intake.md](widget-intake.md).

Use when **changing** a shipped widget type — not when adding a new `widget_type` ([checklist-new-widget-type.md](checklist-new-widget-type.md)).

Reference implementation for patterns: `products/dashboards/frontend/widgets/error_tracking/` (`error_tracking_list`).

Before finishing, apply [skill-maintenance.md](skill-maintenance.md) for any doc updates required by your change.

## What you cannot change in place

- **`widget_type` is immutable** on an existing `DashboardWidget` row. To switch visualization kind, add a new tile (new type) and remove the old one.
- **Stored tile `w` / `h`** are not rewritten when catalog `defaultLayout` changes — only new adds and min/max enforcement on the next layout pass. See [layout-and-ux.md](layout-and-ux.md).

## What kind of change?

| Goal                                   | Primary files                                                                                                                             | Also check                                                                                                                                                                   |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Widget query / `run_widgets` payload   | `backend/widgets/<widget_type>.py`, `widget_registry.py`, `widget_query_throttle.py`                                                      | `test_run_widgets.py`, `test_widget_query_throttle.py`; product listing throttles (replay); **`dashboard_widget_delivery`** SLO (automatic)                                  |
| Config fields (filters, limits, sort)  | `widget_specs/configs.py` (Pydantic SSOT), `WidgetSpec.form_fields`, `Edit*WidgetModal.tsx`, `*WidgetConfigValidation.ts` (API errors)    | `generated/widget-configs.zod.ts`, `hogli build:openapi` (OpenAPI/Zod derive from `WIDGET_SPECS`), registry **`parseConfigApiError`**, MCP catalog `config_schema` snapshots |
| **`run_*` result shape / list footer** | `backend/widgets/<widget_type>.py`, widget `Component` `footer`                                                                           | [list-widget-patterns.md § Pagination footer](list-widget-patterns.md#pagination-footer)                                                                                     |
| **Tile filter bar**                    | `*WidgetTileFilters.tsx`, `widgetTileFiltersHooks.ts`, registry `TileFilters`; mount gated by `hasProductAccess` in `DashboardWidgetItem` | [list-widget-patterns.md](list-widget-patterns.md); debounced refresh via `scheduleRefreshDashboardWidgets` in `dashboardLogic.tsx` listeners                                |
| **ET issue row actions on tile**       | `ErrorTrackingWidget.tsx`, `widgetProductAccess.ts`                                                                                       | Dashboard edit **or** Error tracking Editor; read-only status/assignee when neither                                                                                          |
| **Header title → product scene**       | `catalog.ts` `titleHref`, `WidgetCardHeader.tsx` `isDashboardEditMode`                                                                    | [list-widget-patterns.md § Header title navigation](list-widget-patterns.md#header-title-navigation)                                                                         |
| Tile name / description UX             | `Edit*WidgetModal.tsx`, `EditWidgetModalTileDetailsSection.tsx`                                                                           | Mirror `EditErrorTrackingWidgetModal.tsx` field layout; activity log tests if serializer fields change                                                                       |
| Default size when **adding** a tile    | `catalog.ts` `defaultLayout.w` / `.h`                                                                                                     | `dashboardLogic.addWidgetTiles` (reads catalog defaults)                                                                                                                     |
| **Min/max resize** on dashboard grid   | `catalog.ts` `defaultLayout.minW` / `.minH`                                                                                               | [layout-and-ux.md](layout-and-ux.md) § Tile min/max size — **`tileLayouts.ts`**, `tileLayouts.test.ts`                                                                       |
| Card header / date range display       | `catalog.ts` (`headerLayout`, `headerMeta`, `headerTitle`, `titleHref`)                                                                   | `WidgetCardHeader`, stories                                                                                                                                                  |
| Setup / availability gate              | `catalog.ts` `availability`, `widgetAvailability.ts`                                                                                      | `WidgetRuntimeAvailabilityGuard`; BE `availability_requirements` for MCP catalog                                                                                             |
| RBAC lock on tile                      | `widget_registry.py` `required_product_access`, FE `catalog.ts` `productAccess`                                                           | `types.ts`, `widgetProductAccess.ts` (`WIDGET_PRODUCT_ACCESS_CHECKS`)                                                                                                        |
| Add-modal preview                      | `widgets/previews/` + `DASHBOARD_WIDGET_PREVIEWS` in `widget_types/catalog.ts`                                                            | Reuse demo data from `widgetOverviewStoryFixtures.ts` when possible                                                                                                          |
| Public/shared placeholder copy         | `catalog.ts` **`sharedPlaceholder`**                                                                                                      | `DashboardWidgetItem.test.tsx` public placement; `test_sharing.py`                                                                                                           |
| Agent-facing catalog copy              | `widget_specs/registry.py` `WidgetSpec` (`label`, `description`, `product_access_denied_message`); `config_schema` auto from Pydantic     | `dashboard-widget-catalog-list` / `test_dashboard_widgets.py` catalog assertions                                                                                             |
| Storybook / overview fixtures          | `WidgetCard/*.stories.tsx`, `widgetOverviewStoryFixtures.ts`, `Edit*WidgetModal.stories.tsx`                                              | `getWidgetOverviewDemoState` exhaustive switch per catalog key                                                                                                               |
| Deprecating / removing a type          | See § Deprecating a widget type below                                                                                                     | Orphan tiles fall back to unknown-type UI; keep BE runner until tiles are gone                                                                                               |

Registry parity table (all layers that must stay aligned): [CONTRIBUTING.md § Frontend / backend parity](../../../products/dashboards/CONTRIBUTING.md#frontend--backend-parity).

## Config schema migration (existing tiles)

When changing config shape on tiles already stored in Postgres:

1. **Backward-compatible (preferred)** — in the Pydantic model (`widget_specs/configs.py`), use `model_validator` / field aliases to accept legacy keys; `extra="forbid"` strips unknown keys on validate. Existing tiles keep working without a data migration.
2. **Breaking** — treat as a new `widget_type` (or accept that old tiles may fail validation until users re-save from the edit modal).
3. **Touch every layer** for non-breaking adds/removals:
   - BE: Pydantic model in `widget_specs/configs.py` (or `common.py`)
   - FE: `*WidgetConfigValidation.ts` (form `.pick()` + validation); registry **`parseConfigApiError`**
   - Codegen: `hogli build:openapi` — OpenAPI + `widget-configs.zod.ts` + MCP schemas regenerate from Pydantic (new `widget_type` needs a `*WidgetConfig` Pydantic model + `form_fields` on `WidgetSpec`)
   - Stories/fixtures: component stories, edit modal stories, preview, `widgetOverviewStoryFixtures.ts`
4. **Relative date ranges** — update `backend/constants.py` (`WIDGET_DATE_FROM_VALUES_ORDERED`) and Pydantic `WidgetDateFrom` in `widget_specs/common.py`, then `hogli build:openapi` (regenerates `widget-date-from-options.json`; `widgetConfigShared.ts` re-exports `WIDGET_DATE_RANGE_SELECT_OPTIONS` from that JSON).

## Config update flow (runtime)

1. User opens ⋯ → **Edit** → `Edit*WidgetModal` validates with Zod → `onSave(config, metadataPatch?)` (metadata from `buildWidgetTileMetadataPatch`)
2. `DashboardItems` calls `useAsyncActions(dashboardLogic).updateWidgetTile` so the modal `await onSave(...)` waits for the PATCH
3. `dashboardLogic.updateWidgetTile` → `updateDashboardWidgetTile` → one `dashboardsPartialUpdate` with nested `widget` `{ config, name, description }` and optional `show_description`
4. When `config` changed, `refreshDashboardWidgets` re-runs `run_widgets` for that tile

Guard saves with `loading` / `disabledReason` on Save — never leave the button clickable mid-mutation.

## Edit modal layout

Type-specific edit-modal sections use a 2-column CSS grid (`grid grid-cols-1 sm:grid-cols-2 gap-4`) — copy `EditErrorTrackingWidgetModal.tsx` or `EditWidgetModalTileDetailsSection.tsx`.

- Full-width fields (name, description, test-account filter): put `WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS` (`sm:col-span-2`) on the **grid child** — `LemonField.Pure` or a wrapper `<div>` — **not** on the inner `LemonInput` / `LemonTextArea`.
- Half-width fields (date range, sort, limit): omit `col-span-2`; use `fullWidth` on `LemonSelect` where needed.

Copy `EditErrorTrackingWidgetModal.tsx` Tile details + Filters sections when wiring a new edit modal.

## Changing min/max tile size

Follow [layout-and-ux.md § Tile min/max size](layout-and-ux.md#tile-minmax-size-grid-rows--columns) — catalog `defaultLayout.minW` / `minH` only; changing mins affects all tiles of that type on the next layout pass without rewriting Postgres `h`/`w`.

## Deprecating a widget type

There is no soft-delete for `widget_type` strings. Typical approach:

1. Stop listing the type in FE/BE catalogs and registries (or never ship removal until tiles are migrated).
2. **Keep** `run_*` + registry entry until no production tiles reference the type, **or** accept unknown-type fallback (header + body `ErrorBoundary`, no live data).
3. Update MCP tool schema snapshots and `services/mcp/tests/tools/dashboards.integration.test.ts` when removing from catalog.
4. Update skill docs per [skill-maintenance.md](skill-maintenance.md) if deprecate process changed.

Do not remove backend validation for a type that still has rows in `posthog_dashboardwidget`.

## Verify (updates)

Run [SKILL.md §6 Verify](../SKILL.md#6-verify) for every layer you touched. Prefer targeted paths under `products/dashboards/frontend/widgets/<product>/` and `test_run_widgets.py` when the change is narrow.

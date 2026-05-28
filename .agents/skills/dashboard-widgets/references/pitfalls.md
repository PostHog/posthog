# Pitfalls and troubleshooting

See also: [architecture.md](architecture.md), [permissions-and-sharing.md](permissions-and-sharing.md), [composition.md](composition.md).

## Common mistakes

| Symptom | Fix |
| ------- | --- |
| Data leaks despite frontend `locked` | Set `required_product_access` on the registry entry — backend uses `get_widget_product_access_error` |
| Assumed `required_scopes` is enforced | Registry field is documentation only — RBAC uses `required_product_access` + `widget_access.py` |
| Skeleton in wrong layer | Loading belongs in widget `Component`, not `WidgetCard` shell |
| Body in `gridChildren` | Widget content belongs in composed `WidgetCardBody`; `gridChildren` is RGL resize handles only |
| Fat props on `WidgetCard` | Compose `WidgetCardHeader` + `WidgetCardBody` at callsite — shell is chrome only |
| Add modal missing type | Registry without catalog entry — catalog drives add modal, layouts, headers, previews |
| Backend catalog out of sync | New type needs entries in both `widget_catalog.py` (BE) and `catalog.ts` (FE) |
| Confused `groupId` with `widget_type` | `groupId` groups add-modal UI only; backend/DB need a unique `widget_type` per variant |
| Reused `widget_type` for a new variant | Each variant needs its own catalog key + BE/FE registry entry — do not overload an existing type |
| Inconsistent `groupLabel` within a group | All entries sharing a `groupId` must use the same `groupLabel` |
| CI fails on widget types | Keep `EXPECTED_WIDGET_TYPES` in sync with `WIDGET_REGISTRY`; extend `DashboardWidgetType` when adding a canonical type |
| Frontend types drift | Run `hogli build:openapi` after serializer changes |
| Filter toggle in ⋯ menu | `filterTestAccounts` belongs in settings modal Filters section — wire `TestAccountFilter` (or equivalent) in a `WidgetSettingsModalSection`; baked into `baseWidgetConfigSchema` / `merge_base_widget_config_fields` |
| Inline title/description edit on card | Title and description edit only in widget settings modal Tile details section |
| Storybook "CSF: unexpected dynamic title" | Meta `title` must be a string literal matching catalog `groupLabel` / `label` — no helper function in CSF |
| Unknown `widget_type` crashes render | Every supported type needs a registry entry; unsupported types should not reach render |
| Unknown `widget_type` renders empty tile | `getDashboardWidgetDefinition` dedupes a PostHog `captureException` per canonical type — add the registry entry (and keep catalog in sync) |
| Widget CRUD tests fail with validation errors | Copy the setUp patch pattern from existing widget test modules |
| Empty test file scaffold | Do not commit `.test.tsx` files with only `@testing-library/jest-dom` import — add real assertions or omit the file |
| Modified product SetupPrompt for widgets | Add setup gate UI inside `widgets/<product>/<Component>.tsx` instead |
| Added widget props to `ProductIntroduction` | Use `WidgetCardProductIntroduction` in the dashboard widget layer instead |
| Hardcoded product check in `DashboardWidgetItem` | Extend `userHasWidgetProductAccess` switch + `DashboardWidgetProductAccess` union — one `case` per gated product |
| Hardcoded product check in `dashboard.py` | Set `required_product_access` on registry entry — use `widget_access.py` |
| Missing FE RBAC map entry | Extend `DashboardWidgetProductAccess` union + `DASHBOARD_WIDGET_PRODUCT_ACCESS_RESOURCES` |
| Fetch error shows raw API string | Add passthrough prefix in `constants.ts` (`getDashboardWidgetFetchDisplayError`) or rely on generic message |
| Resize floor stuck at 4 rows | Catalog entry missing `minH` — `tileLayouts.ts` falls back to `MIN_WIDGET_TILE_HEIGHT_ROWS` (4). Set explicit `defaultLayout.minH` in `catalog.ts` + test in `tileLayouts.test.ts` |
| Changed min size in widget component / SCSS | Mins are **catalog → `tileLayouts.ts` → RGL**, not the widget body. See [layout-and-ux.md](layout-and-ux.md) § Tile min/max size |
| Description/name half-width in edit modal | `WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS` must be on `LemonField.Pure` (grid child), not on inner `LemonInput`/`LemonTextArea` — copy `EditErrorTrackingWidgetModal.tsx` |
| `TestAccountFilter` crashes edit modal | Pass `filters={{ filter_test_accounts }}` and `onChange={({ filter_test_accounts }) => …}` — not `checked`/`onChange(boolean)` |

See [scaling.md](scaling.md) for what should vs should not grow per widget type.

## "If you change X, also check Y"

| Change | Verify |
| ------ | ------ |
| New `widget_type` in backend registry | Frontend registry + catalog + preview + `EXPECTED_WIDGET_TYPES` test |
| New variant in existing product group | Unique `widget_type`; reuse `groupId`/`groupLabel`; distinct `label`/`defaultConfig`/`defaultLayout`; full BE+FE stack still required |
| `run_widgets` permission logic | `required_product_access` on registry entry; `test_run_widgets.py` + `test_widget_access.py`; `DashboardWidgetItem.test.tsx` for FE lock state |
| Storybook setup states all look the same | Check decorator stacking — meta-level `withErrorTrackingProjectState(true)` overrides story-level `false`; seed per story |
| Serializer field on `DashboardWidget` | `hogli build:openapi`; generated types; activity logging |
| Catalog `defaultLayout` | `tileLayouts.ts` min/max; `tileLayouts.test.ts` case for `expectedMinH`/`minW`; RGL resize in edit mode; optional Storybook `MinimumSize` story |
| Widget `Component` loading path | Skeleton in component only; shell still resizes correctly |
| Copy/move tile logic | Widget copy deep-clones; move reassigns tile. Button tiles still blocked cross-dashboard |
| Date range options | Keep `widgetDateRangeOptions.ts`, Zod schema, and edit-modal select in sync |
| Multi-tile add (UI / MCP) | `addWidgetTiles` → `POST .../widgets/batch/` |
| REST/MCP single add | `POST .../widgets/` creates one tile per request |

## `run_widgets` permission pattern

The `required_scopes` field on registry entries documents expected scopes. RBAC is enforced via `required_product_access` on each `WIDGET_REGISTRY` entry — `get_widget_product_access_error` in `widget_access.py` handles `run_widgets` and tile mutations. Do not add per-type `if widget_type == …` branches in `dashboard.py`.

## Out of scope

Insight tiles, text cards, and button tiles use separate models. Widgets are the path for **new** embeddable content types only.

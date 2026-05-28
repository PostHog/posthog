# Scaling to many widget types

Platform glue stays product-agnostic. Each new type adds files under product-specific paths — not branches in shared dispatch code.

## Per-type touch list (typical add)

| Layer | Add / extend |
| ----- | ------------ |
| BE runtime | `backend/widgets/<widget_type>.py` — `validate_*`, `run_*` |
| BE registry | `widget_registry.py` — one `WIDGET_REGISTRY` key + `DashboardWidgetType` |
| BE catalog | `widget_catalog.py` — one `WIDGET_CATALOG` entry |
| BE access | `widget_access.py` — denial message in `PRODUCT_ACCESS_DENIED_MESSAGES` (optional) |
| FE catalog | `widget_types/catalog.ts` — one key (`satisfies` forces registry sync) |
| FE config | `configSchemas.ts` — per-type Zod schema (split into `configSchemas/<product>.ts` when file grows) |
| FE registry | `widgets/registry.tsx` — import `Component` / `EditModal` from `widgets/<product>/`; one keyed entry per `widget_type` |
| FE RBAC | `types.ts` `DashboardWidgetProductAccess` union + new `case` in `userHasWidgetProductAccess` (`DashboardWidgetItem.tsx`) |
| FE preview | `widgets/previews/` + `widgetPreviews.tsx` key |
| FE widget | `widgets/<product>/` — Component, EditModal, stories, tests |
| FE overview demo | `widgetOverviewStoryFixtures.ts` — one `case` in exhaustive switch |

## Files that should **not** grow per type

| File | Role |
| ---- | ---- |
| `dashboard.py` `run_widgets` | Generic loop — uses `get_widget_registry_entry` + `get_widget_product_access_error` |
| `DashboardWidgetItem.tsx` | Generic shell — composes `WidgetCard` + header/body; extend `userHasWidgetProductAccess` switch only when adding a new gated product |
| `WidgetCard.tsx` | Thin chrome shell only — no product imports, no header/body props |
| `WidgetCardHeader.tsx` / `WidgetCardBody.tsx` | Shared compound parts — no product imports |
| `dashboardLogic.tsx` | Generic fetch/CRUD — no `widget_type` switches for data |
| `widgetFetchUtils.ts` | Batched `run_widgets` only |

## Type-safety nets (CI)

- BE: `EXPECTED_WIDGET_TYPES == WIDGET_REGISTRY.keys()`
- FE: `DASHBOARD_WIDGET_REGISTRY satisfies Record<DashboardWidgetCatalogKey, …>`
- FE: `DASHBOARD_WIDGET_PREVIEWS` keyed by `DashboardWidgetCatalogKey`
- FE: `registry.test.tsx` — every catalog key has a definition
- Runtime: `getDashboardWidgetDefinition` → PostHog `captureException` on miss (deploy skew)

## Variants in the same product group

Multiple `widget_type` entries share `groupId` / `groupLabel` in catalog only. `AddWidgetModal` groups by `groupId` inline — no separate grouping module. Each variant still gets the full per-type stack above — **no** shared `if widget_type in (...)` permission or query branches in platform code.

## Registry imports

Import `Component` and `EditModal` directly in `registry.tsx` (no `React.lazy`, no per-type `definition.ts`). `DashboardWidgetItem` renders components directly — widget-owned `WidgetLoadingState` handles data-fetch loading.

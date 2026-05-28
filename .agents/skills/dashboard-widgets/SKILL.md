---
name: dashboard-widgets
description: >
  Agent playbook for PostHog dashboard widget types — add new types or update existing ones
  (config, edit modal, catalog layout mins, run_widgets, stories). Covers backend WIDGET_REGISTRY,
  frontend catalog/registry, WidgetCard composition, permissions, and dashboard scene glue.
  Load when adding or modifying dashboard widget types, changing tile min/default size, WIDGET_REGISTRY,
  DASHBOARD_WIDGET_CATALOG, WidgetCard, run_widgets, edit/settings modals, or dashboard tile widget glue.
---

# Managing dashboard widgets

Add new embeddable types **or update existing ones** (config, layout mins, edit modal, query, stories).

Embeddable dashboard content types backed by `DashboardWidget` + `run_widgets`.
Overview: [`products/dashboards/CONTRIBUTING.md`](../../../products/dashboards/CONTRIBUTING.md)

Reference implementation: `products/dashboards/frontend/widgets/error_tracking/`

**Out of scope:** insight tiles, text cards, button tiles — separate models today.

## Pattern index

| You want to… | Read |
| ------------ | ---- |
| **Add** a new widget type (`widget_type` + JSON `config`) | [checklist-new-widget-type.md](references/checklist-new-widget-type.md) end-to-end |
| **Update** an existing type (config, modal, mins, query, stories) | [managing-existing-widgets.md](references/managing-existing-widgets.md) |
| Change tile **min/default size** on the dashboard grid | [layout-and-ux.md](references/layout-and-ux.md) § Tile min/max size |
| Add a second variant in an existing product group | [checklist-new-widget-type.md](references/checklist-new-widget-type.md) §4b (variant pattern) |
| Understand tile/widget model or registries | [architecture.md](references/architecture.md) |
| Compose WidgetCard, loading, RGL, headers | [composition.md](references/composition.md) |
| Wire RBAC, copy/move, or shared dashboards | [permissions-and-sharing.md](references/permissions-and-sharing.md) |
| Gate on project setup or show setup prompts | [availability-and-gating.md](references/availability-and-gating.md) |
| Set grid sizing, menus, or undo remove | [layout-and-ux.md](references/layout-and-ux.md) |
| Debug a bug | [pitfalls.md](references/pitfalls.md) |
| Add type N — what grows vs stays generic | [scaling.md](references/scaling.md) |
| Expose widgets via MCP / agent tools | [mcp.md](references/mcp.md) |
| Find the right file to edit | [file-paths.md](references/file-paths.md) |

## Unbreakable rules

1. **Product RBAC is registry-driven** — set `required_product_access` on each `WIDGET_REGISTRY` entry (and matching `productAccess` on FE catalog). Extend `DashboardWidgetProductAccess` in `types.ts` and the `userHasWidgetProductAccess` switch in `DashboardWidgetItem.tsx`. `get_widget_product_access_error` handles `run_widgets` and tile mutations. **Never** add per-type `if widget_type == …` in `dashboard.py`. `required_scopes` is documentation only.
2. **Catalog + registry must match** — catalog drives add modal, layouts, headers, previews; `DASHBOARD_WIDGET_REGISTRY` uses `satisfies Record<DashboardWidgetCatalogKey, …>`. Each variant needs a unique `widget_type`; variants in the same product area share `groupId`/`groupLabel` (see [architecture.md](references/architecture.md)).
3. **Compound `WidgetCard`** — thin shell only; compose `WidgetCardHeader` + `WidgetCardBody` at the callsite (`DashboardWidgetItem`, stories). Widget content goes in `WidgetCardBody`; RGL resize handles go in `gridChildren`. Loading lives in the widget `Component`, not the shell.
4. **Cross-dashboard copy/move deep-clones widgets** — copy creates a new `DashboardWidget` row; move reassigns the tile row. Dashboard duplication always deep-clones widget rows.
5. **Title, description, and filters live in the widget settings modal** — compose `WidgetSettingsModalSection` blocks inside `WidgetSettingsModalSections` (Tile details / Filters / type-specific). Not inline on the card header; `filterTestAccounts` is not in the ⋯ menu. Full-width fields: `WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS` on the **grid child** (`LemonField.Pure`), not the inner input — see [managing-existing-widgets.md](references/managing-existing-widgets.md).
6. **Tile min/max size is catalog → `tileLayouts.ts`** — set `defaultLayout.minH` / `minW` in `catalog.ts`; do not try to fix resize floors in the widget component. See [layout-and-ux.md](references/layout-and-ux.md) § Tile min/max size.
7. **New `widget_type` strings need no migration** — register backend + frontend + both catalogs; invoke `django-migrations` only for schema changes.
8. **No product-specific glue** — validate/run live in `backend/widgets/<type>.py`; UI in `frontend/widgets/<product>/`. Do not hardcode product names in `DashboardWidgetItem`, `WidgetCard`, or `run_widgets`.

## Mandatory companion skills

Invoke **before** editing their files:

| Skill | Files |
| ----- | ----- |
| `improving-drf-endpoints` | `products/dashboards/backend/api/dashboard.py` serializers/actions |
| `writing-kea-logics` | `frontend/src/scenes/dashboard/dashboardLogic.tsx` |
| `django-migrations` | `DashboardWidget` / `DashboardTile` schema changes only |
| `implementing-mcp-tools` | `products/dashboards/mcp/tools.yaml`, widget MCP endpoints |
| `adopting-generated-api-types` | Migrating manual API client calls |

## Architecture (sketch)

```text
DashboardTile (layout) → widget_id → DashboardWidget (team-scoped)
  widget_type + config  →  WIDGET_REGISTRY (BE)  →  run_widgets
                        →  DASHBOARD_WIDGET_CATALOG + registry.tsx (FE)
                        →  tileLayouts.ts (defaultLayout → RGL minW/minH)
```

Full layer table and registry shapes: [architecture.md](references/architecture.md)

## Pre-change checklist

**Adding a type**

- [ ] Read [checklist-new-widget-type.md](references/checklist-new-widget-type.md)
- [ ] Mirror `error_tracking_list` unless you have a strong reason not to
- [ ] Set explicit `defaultLayout.minW` / `minH` on the catalog entry (do not rely on `MIN_WIDGET_TILE_HEIGHT_ROWS = 4` fallback)

**Updating a type**

- [ ] Read [managing-existing-widgets.md](references/managing-existing-widgets.md) for the change class (config vs mins vs modal vs query)
- [ ] If changing mins: catalog + `tileLayouts.test.ts` — not the widget component
- [ ] If changing edit modal: mirror `EditErrorTrackingWidgetModal.tsx` grid layout

**Always**

- [ ] Backend: `widgets/<widget_type>.py` + `required_product_access` on registry entry (not manual checks in `dashboard.py`)
- [ ] Frontend: `registry.tsx` entry + catalog entry + `widgetPreviews` + `DashboardWidgetProductAccess` union + `userHasWidgetProductAccess` case when RBAC-gated
- [ ] After serializer changes: `hogli build:openapi` (do not edit generated files)
- [ ] Run backend + frontend tests in **Verify** below

## Verify

```bash
# Backend
hogli test products/dashboards/backend/api/test/test_dashboard_widgets.py
hogli test products/dashboards/backend/api/test/test_run_widgets.py
hogli test products/dashboards/backend/api/test/test_widget_access.py

# Frontend
hogli test products/dashboards/frontend/widgets/
hogli test frontend/src/scenes/dashboard/tileLayouts.test.ts
hogli test products/dashboards/frontend/components/DashboardWidgetItem/DashboardWidgetItem.test.tsx
hogli test products/dashboards/frontend/components/WidgetCard/

# Storybook (widget loading / empty / populated / minimum size states)
pnpm storybook
```

Schema migrations chain after `0006_migrate_product_analytics_models` (`products/dashboards/backend/migrations/`).

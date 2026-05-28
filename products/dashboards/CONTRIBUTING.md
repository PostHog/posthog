# Dashboard widgets

Embeddable dashboard tiles backed by `DashboardWidget` and rendered through the product-local frontend registry in `products/dashboards/frontend/`.

**In scope:** widget tiles (`widget_id` on `DashboardTile`).
**Out of scope:** insight tiles, text cards, and button tiles — separate models today.

Reference implementation: `products/dashboards/frontend/widgets/error_tracking/` (`error_tracking_list`).

## Architecture (sketch)

```text
DashboardTile (layout) → widget_id → DashboardWidget (team-scoped)
  widget_type + config  →  WIDGET_REGISTRY (BE)  →  run_widgets
                        →  DASHBOARD_WIDGET_CATALOG + registry.tsx (FE)
```

New `widget_type` strings need **no migration** — register backend + frontend + both catalogs.
Schema changes on `DashboardWidget` / `DashboardTile` use the dashboards migration chain (`0007+` after `0006_migrate_product_analytics_models`).

Layer table, registry shapes, copy/move, analytics, and typing details: [`.agents/skills/dashboard-widgets/references/architecture.md`](../../.agents/skills/dashboard-widgets/references/architecture.md)

## Playbook

**Canonical guide:** [`.agents/skills/dashboard-widgets/`](../../.agents/skills/dashboard-widgets/) (also loaded by agents via `/dashboard-widgets` — covers **add and update**).

| Task | Doc |
| ---- | --- |
| Add a new widget type | [`references/checklist-new-widget-type.md`](../../.agents/skills/dashboard-widgets/references/checklist-new-widget-type.md) |
| Update an existing widget type | [`references/managing-existing-widgets.md`](../../.agents/skills/dashboard-widgets/references/managing-existing-widgets.md) |
| Tile min/max size on dashboard grid | [`references/layout-and-ux.md`](../../.agents/skills/dashboard-widgets/references/layout-and-ux.md) (§ Tile min/max size) |
| WidgetCard, loading, headers | [`references/composition.md`](../../.agents/skills/dashboard-widgets/references/composition.md) |
| RBAC, copy/move, shared dashboards | [`references/permissions-and-sharing.md`](../../.agents/skills/dashboard-widgets/references/permissions-and-sharing.md) |
| Scaling to many widget types | [`references/scaling.md`](../../.agents/skills/dashboard-widgets/references/scaling.md) |
| MCP / REST | [`references/mcp.md`](../../.agents/skills/dashboard-widgets/references/mcp.md) |
| Pitfalls | [`references/pitfalls.md`](../../.agents/skills/dashboard-widgets/references/pitfalls.md) |
| File index | [`references/file-paths.md`](../../.agents/skills/dashboard-widgets/references/file-paths.md) |

**Critical rule:** set `required_product_access` / `productAccess` only when the widget reads gated product data — omit both when no extra product RBAC is needed. Platform glue stays generic. `required_scopes` is documentation only.

## Frontend / backend parity

Three registries must stay aligned for every shipped `widget_type`:

| Registry | Location |
| -------- | -------- |
| `EXPECTED_WIDGET_TYPES` | `backend/widget_registry.py` |
| `WIDGET_CATALOG` | `backend/widget_catalog.py` |
| `DASHBOARD_WIDGET_CATALOG` | `frontend/widget_types/catalog.ts` |

Each catalog key equals the canonical `widget_type` string. On the frontend,
`DASHBOARD_WIDGET_REGISTRY` uses `satisfies Record<DashboardWidgetCatalogKey, …>`
so a missing registry entry fails TypeScript. `registry.test.tsx` asserts catalog
keys match `EXPECTED_DASHBOARD_WIDGET_TYPES` (keep in sync with the Python
constant). Backend tests assert `WIDGET_REGISTRY`, `WIDGET_CATALOG`, and
`EXPECTED_WIDGET_TYPES` match. After adding a type, run both backend and frontend
widget tests in **Verify** below.

## Adding a widget type

Full step-by-step: [checklist-new-widget-type.md](../../.agents/skills/dashboard-widgets/references/checklist-new-widget-type.md).

Each registry below grows with one entry per `widget_type`. Inline comments in code point here instead of repeating the list.

| Location | What to add |
| -------- | ----------- |
| `backend/widgets/<widget_type>.py` | `validate_*` + `run_*` for the type |
| `backend/widget_registry.py` | `WIDGET_REGISTRY` key, `EXPECTED_WIDGET_TYPES`, `DashboardWidgetType`, optional `WIDGET_TYPE_ALIASES` / `DashboardWidgetTypeInput` |
| `backend/widget_catalog.py` | `WIDGET_CATALOG` key |
| `backend/widget_access.py` | Optional friendly `PRODUCT_ACCESS_DENIED_MESSAGES` entry per shipped gated type |
| `frontend/widget_types/catalog.ts` | `DASHBOARD_WIDGET_CATALOG` key; optional `DASHBOARD_WIDGET_TYPE_ALIASES` |
| `frontend/widget_types/configSchemas.ts` | Per-type Zod schema (used by catalog `defaultConfig`) |
| `frontend/widget_types/widgetConfigValidation.ts` | Shared validation error type |
| `frontend/widgets/<product>/*WidgetConfigValidation.ts` | Per-type edit-modal validation |
| `frontend/types.ts` | `DashboardWidgetProductAccess` union member (if RBAC-gated) |
| `frontend/components/DashboardWidgetItem/DashboardWidgetItem.tsx` | `userHasWidgetProductAccess` case (if RBAC-gated) |
| `frontend/widgets/registry.tsx` | `DASHBOARD_WIDGET_REGISTRY` key |
| `frontend/widgets/previews/widgetPreviews.tsx` | Preview component + map entry |
| `frontend/components/WidgetCard/widgetOverviewStoryFixtures.ts` | `getWidgetOverviewDemoState` switch case |
| `frontend/widget_types/widgetAvailability.ts` | `WidgetAvailabilityRequirementId` + evaluator (if catalog uses `availability`) |
| `frontend/components/WidgetAvailabilitySetupPrompt/` | Setup UI branch for new requirement id |

Auto-derived from catalog (no manual list edit): add-widget modal grouping, overview story tile list, `DashboardWidgetCatalogKey` type.

## Verify

```bash
hogli test products/dashboards/backend/api/test/test_dashboard_widgets.py
hogli test products/dashboards/backend/api/test/test_run_widgets.py
hogli test products/dashboards/backend/api/test/test_widget_access.py
hogli test products/dashboards/frontend/widgets/
hogli test products/dashboards/frontend/components/DashboardWidgetItem/DashboardWidgetItem.test.tsx
hogli test products/dashboards/frontend/components/WidgetCard/
```

After serializer changes: `hogli build:openapi` (do not edit `products/dashboards/frontend/generated/`).

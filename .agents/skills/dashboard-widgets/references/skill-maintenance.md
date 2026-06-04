# Skill maintenance (keep docs in sync)

**Same PR as the code change** when agent-facing behavior or contributor workflow changes. Registry parity is CI-enforced in code tests — do not hand-maintain type lists in markdown.

## Doc architecture (avoid duplication)

One canonical home per topic — link elsewhere; do not copy tables or long prose.

| Topic                        | Canonical doc                                                                                                     |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Intake / spec questions      | [widget-intake.md](widget-intake.md)                                                                              |
| Add flow (files + order)     | [checklist-new-widget-type.md](checklist-new-widget-type.md)                                                      |
| Model, naming, scaling rules | [architecture.md](architecture.md)                                                                                |
| Product RBAC                 | [permissions-and-sharing.md § Product RBAC](permissions-and-sharing.md#product-rbac)                              |
| Tile min/max size            | [layout-and-ux.md § Tile min/max size](layout-and-ux.md#tile-minmax-size-grid-rows--columns)                      |
| Registry entry shapes (code) | [architecture.md](architecture.md)                                                                                |
| Update flow                  | [managing-existing-widgets.md](managing-existing-widgets.md) — [SKILL.md §3](../SKILL.md#3-update-a-shipped-type) |
| Verify commands              | [SKILL.md §6 Verify](../SKILL.md#6-verify)                                                                        |
| Human entry / nav            | [`products/dashboards/CONTRIBUTING.md`](../../../products/dashboards/CONTRIBUTING.md)                             |

## When this applies

Load `/dashboard-widgets` and complete the maintenance checklist below when **any** of these change:

| Trigger path (glob)                                              | Examples                                                        |
| ---------------------------------------------------------------- | --------------------------------------------------------------- |
| `products/dashboards/backend/widgets/**`                         | New `run_*`, config validation, query wiring                    |
| `products/dashboards/backend/widget_registry.py`                 | New/removed `widget_type`                                       |
| `products/dashboards/backend/widget_catalog.py`                  | Labels, hints, availability strings                             |
| `products/dashboards/backend/api/widget_openapi_serializers.py`  | Config OpenAPI shapes                                           |
| `products/dashboards/backend/api/dashboard.py`                   | `run_widgets`, batch add, sharing serializers (generic only)    |
| `products/dashboards/backend/widget_query_throttle.py`           | Per-team burst/sustained caps on `run_widgets`                  |
| `products/dashboards/backend/widget_access.py`                   | RBAC denial copy                                                |
| `products/dashboards/frontend/widgets/**`                        | Component, edit modal, registry, previews                       |
| `products/dashboards/frontend/widget_types/**`                   | Catalog, Zod schemas, availability                              |
| `products/dashboards/frontend/components/WidgetCard/**`          | Shared tile chrome, placeholders, overview fixtures             |
| `products/dashboards/frontend/components/DashboardWidgetItem/**` | Tile glue, public placement, `TileFilters` mount                |
| `products/dashboards/frontend/widgets/constants.ts`              | List footer, fetch errors, tile refresh debounce ms             |
| `frontend/src/scenes/dashboard/widgetTileRefreshScheduler.ts`    | Debounced `run_widgets` after tile filter PATCH                 |
| `frontend/src/scenes/dashboard/dashboardLogic.tsx`               | `scheduleRefreshDashboardWidgets` vs immediate refresh          |
| `products/dashboards/frontend/widgets/*WidgetTileFilters.tsx`    | On-tile filters (date, status, property pickers)                |
| `frontend/src/scenes/dashboard/DashboardItems.tsx`               | `showEditingControls`, `isDashboardEditMode`, tile filter mount |
| `products/dashboards/mcp/tools.yaml`                             | Widget MCP tools                                                |
| `frontend/src/scenes/dashboard/tileLayouts.ts`                   | Layout algorithm (only if behavior/docs change)                 |
| `posthog/api/test/test_sharing.py`                               | Shared dashboard widget payload expectations                    |
| `tach.toml` (`products.dashboards` `depends_on`)                 | New product import boundary                                     |

Platform-only refactors with **no** behavior or agent-facing surface change may skip narrative updates — still run Verify tests.

## Change → doc map

| You changed                                | Update in this skill                                                                                                                           |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| New or removed **`widget_type`**           | [checklist-new-widget-type.md](checklist-new-widget-type.md) if add flow shifted; [architecture.md](architecture.md) footguns if new invariant |
| Config fields / validation                 | [managing-existing-widgets.md](managing-existing-widgets.md) § Config schema migration                                                         |
| Public/shared/export behavior              | [permissions-and-sharing.md](permissions-and-sharing.md); SKILL.md §4 invariants                                                               |
| Setup / availability gating                | [availability-and-gating.md](availability-and-gating.md); BE `availability_requirements` note                                                  |
| Tile layout / mins / add placement         | [layout-and-ux.md](layout-and-ux.md); [architecture.md](architecture.md) if REST/MCP add path changed                                          |
| WidgetCard / edit modal composition        | [composition.md](composition.md)                                                                                                               |
| Tile filter bar / `widgetFilters` config   | [composition.md](composition.md) § Widget settings modal + § List widget patterns                                                              |
| List pagination footer / `run_*` totals    | [composition.md](composition.md) § List widget patterns (`include_total_count` on dashboard path)                                              |
| `run_widgets` rate limits                  | [composition.md](composition.md) or [architecture.md](architecture.md); `widget_query_throttle.py` + product listing throttles (replay)        |
| Debounced tile refresh after filter PATCH  | `constants.ts` `WIDGET_TILE_REFRESH_DEBOUNCE_MS`; `dashboardLogic.tsx`                                                                         |
| Header title link / dashboard edit mode    | [composition.md](composition.md) § List widget patterns; [layout-and-ux.md](layout-and-ux.md) § ⋯ menu parity                                  |
| MCP tools or agent flows                   | [mcp.md](mcp.md)                                                                                                                               |
| New product area / tach / UI reuse pattern | [checklist-new-widget-type.md](checklist-new-widget-type.md) §4c                                                                               |
| Human contributor entry point              | [`products/dashboards/CONTRIBUTING.md`](../../../products/dashboards/CONTRIBUTING.md) registry table / Verify block                            |

Prefer **editing an existing reference** over adding a new file. Keep `SKILL.md` as the index — move detail into `references/`.

## Add checklist (new `widget_type`)

Minimum doc updates — full code checklist in [checklist-new-widget-type.md](checklist-new-widget-type.md):

1. [ ] [checklist-new-widget-type.md](checklist-new-widget-type.md) — update if the add flow or easy-to-miss paths changed
2. [ ] [architecture.md](architecture.md) — footguns or platform invariants if you discovered a new one worth documenting
3. [ ] `CONTRIBUTING.md` — if Verify commands or registry parity table changed

## Update checklist (existing type)

1. [ ] [managing-existing-widgets.md](managing-existing-widgets.md) — extend routing table or migration notes if the change is reusable
2. [ ] `mcp.md` — if agent workflow or tool semantics changed

## Remove / deprecate a type

1. [ ] Remove from registries first only when no tiles remain (or document unknown-type fallback)
2. [ ] Add note under [managing-existing-widgets.md](managing-existing-widgets.md) § Deprecating if process changed

## Verify doc + code together

```bash
hogli test products/dashboards/backend/api/test/test_run_widgets.py
hogli test products/dashboards/backend/api/test/test_dashboard_widgets.py
hogli test products/dashboards/frontend/widgets/registry.test.tsx
```

After OpenAPI/MCP changes, also run [SKILL.md §6 Verify](../SKILL.md#6-verify).

## What not to duplicate

- **Runtime truth** stays in code + tests (`EXPECTED_WIDGET_TYPES`, catalog keys, `registry.test.tsx`). Do not maintain parallel type lists in markdown.
- **Generated files** (`frontend/generated/*`, MCP schema JSON) — regen with `hogli build:openapi`, do not document field-by-field copies.

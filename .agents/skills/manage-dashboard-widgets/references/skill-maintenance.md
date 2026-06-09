# Skill maintenance (keep docs in sync)

**Same PR as the code change** when agent-facing behavior or contributor workflow changes. Registry parity is CI-enforced in code tests — do not hand-maintain type lists in markdown.

## Doc architecture (avoid duplication)

One canonical home per topic — link elsewhere; do not copy tables or long prose.

| Topic                        | Canonical doc                                                                                                     |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Intake / spec questions      | [widget-intake.md](widget-intake.md)                                                                              |
| Add flow (files + order)     | [checklist-new-widget-type.md](checklist-new-widget-type.md)                                                      |
| Model, naming, scaling rules | [architecture.md](architecture.md)                                                                                |
| Config contract / codegen    | [config-and-codegen.md](config-and-codegen.md)                                                                    |
| Codegen & CI (local + drift) | [config-and-codegen.md § Codegen & CI](config-and-codegen.md#codegen--ci)                                         |
| Product RBAC                 | [permissions-and-sharing.md § Product RBAC](permissions-and-sharing.md#product-rbac)                              |
| Tile min/max size            | [layout-and-ux.md § Tile min/max size](layout-and-ux.md#tile-minmax-size-grid-rows--columns)                      |
| Registry entry shapes (code) | [architecture.md](architecture.md)                                                                                |
| Update flow                  | [managing-existing-widgets.md](managing-existing-widgets.md) — [SKILL.md §3](../SKILL.md#3-update-a-shipped-type) |
| Verify commands              | [SKILL.md §6 Verify](../SKILL.md#6-verify)                                                                        |
| Human entry / nav            | [`products/dashboards/CONTRIBUTING.md`](../../../products/dashboards/CONTRIBUTING.md)                             |

## When this applies

Load `/manage-dashboard-widgets` and complete the maintenance checklist below when **any** of these change:

| Trigger path (glob)                                                        | Examples                                                                                       |
| -------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `products/dashboards/backend/widgets/**`                                   | New `run_*`, config validation, query wiring                                                   |
| `products/dashboards/backend/widget_specs/**`                              | Pydantic config models, validation, OpenAPI, registry manifest                                 |
| `products/dashboards/backend/widget_specs/pydantic_openapi.py`             | `model_json_schema()` injection, `DashboardWidgetConfig` `oneOf` for Orval                     |
| `products/dashboards/backend/widget_registry.py`                           | Re-exports only — edit `widget_specs/registry.py`                                              |
| `products/dashboards/backend/widget_catalog.py`                            | Derived catalog — edit `registry.py` `WidgetSpec` for labels/availability                      |
| `products/dashboards/backend/api/widget_openapi_serializers.py`            | Re-exports — OpenAPI serializers derive from `WIDGET_SPECS`                                    |
| `products/dashboards/backend/api/test/dashboard_openapi_test_helpers.py`   | Dashboard PATCH OpenAPI contract exclusions for `test_dashboard_openapi.py`                    |
| `bin/build-dashboard-widget-types.py`                                      | `widget-date-from-options.json`, `widget-form-fields.json`, ENUM preflight from `WIDGET_SPECS` |
| `tools/openapi-codegen/package.json` (`orval` version)                     | Widget catalog Zod requires Orval 8.14+ `generateReusableSchemas`                              |
| `tools/openapi-codegen/src/zod-postprocess.mjs`                            | `fixNullDefaults`, `annotatePureZodExports` — shared Orval Zod postprocess                     |
| `tools/openapi-codegen/src/schema.mjs`                                     | `discoverComponentSchemaNames`, `discoverCatalogEntryConfigPropertyKeys`                       |
| `products/dashboards/frontend/bin/generate-widget-config-zod.mjs`          | Orval `generateReusableSchemas` → `widget-config-schemas/*.zod.ts` + `widget-configs.zod.ts`   |
| `products/dashboards/backend/api/test/test_widget_config_schema_parity.py` | Catalog `config_schema` ↔ Pydantic parity                                                      |
| `products/dashboards/frontend/widgets/widgetConfigSchemaParity.test.ts`    | FE Zod keys ↔ `widget-config-property-keys.json`                                               |
| `posthog/openapi/enum_collisions.py`                                       | Shared enum collision logic for `find_enum_collisions` + CI                                    |
| `products/dashboards/backend/api/dashboard.py`                             | `run_widgets`, batch add, sharing serializers (generic only)                                   |
| `products/dashboards/backend/widget_query_throttle.py`                     | Per-team burst/sustained caps on `run_widgets`                                                 |
| `products/dashboards/backend/widget_access.py`                             | RBAC denial copy                                                                               |
| `products/dashboards/frontend/widgets/**`                                  | Component, edit modal, registry, previews                                                      |
| `products/dashboards/frontend/widget_types/**`                             | Catalog, `widgetConfigShared.ts` UI labels, availability                                       |
| `products/dashboards/frontend/generated/widget-config-*.ts`                | Regen only — do not hand-edit; update architecture/checklist if codegen outputs change         |
| `products/dashboards/frontend/generated/widget-config-schemas/**`          | Orval reusable per-component Zod — regen via `hogli build:widget-types`                        |
| `posthog/settings/web.py` (`ENUM_NAME_OVERRIDES`)                          | New per-type `widget_type` OpenAPI enum collision overrides                                    |
| `products/dashboards/frontend/components/WidgetCard/**`                    | Shared tile chrome, placeholders, overview fixtures                                            |
| `products/dashboards/frontend/components/DashboardWidgetItem/**`           | Tile glue, public placement, `TileFilters` mount                                               |
| `products/dashboards/frontend/widgets/constants.ts`                        | List footer, fetch errors, tile refresh debounce ms                                            |
| `frontend/src/scenes/dashboard/widgetTileRefreshScheduler.ts`              | Debounced `run_widgets` after tile filter PATCH                                                |
| `frontend/src/scenes/dashboard/dashboardLogic.tsx`                         | `scheduleRefreshDashboardWidgets` vs immediate refresh                                         |
| `products/dashboards/frontend/widgets/*WidgetTileFilters.tsx`              | On-tile filters (date, status, property pickers)                                               |
| `frontend/src/scenes/dashboard/DashboardItems.tsx`                         | `showEditingControls`, `isDashboardEditMode`, tile filter mount                                |
| `products/dashboards/mcp/tools.yaml`                                       | Widget MCP tools                                                                               |
| `frontend/src/scenes/dashboard/tileLayouts.ts`                             | Layout algorithm (only if behavior/docs change)                                                |
| `posthog/api/test/test_sharing.py`                                         | Shared dashboard widget payload expectations                                                   |
| `tach.toml` (`products.dashboards` `depends_on`)                           | New product import boundary                                                                    |

Platform-only refactors with **no** behavior or agent-facing surface change may skip narrative updates — still run Verify tests.

## Change → doc map

| You changed                                | Update in this skill                                                                                                                                                                                             |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| New or removed **`widget_type`**           | [checklist-new-widget-type.md](checklist-new-widget-type.md) if add flow shifted; [config-and-codegen.md § Codegen & CI](config-and-codegen.md#codegen--ci) for `ENUM_NAME_OVERRIDES`; footguns if new invariant |
| Config fields / validation                 | [config-and-codegen.md](config-and-codegen.md); [managing-existing-widgets.md](managing-existing-widgets.md) § Config schema migration; parity tests in [SKILL.md §6 Verify](../SKILL.md#6-verify)               |
| Public/shared/export behavior              | [permissions-and-sharing.md](permissions-and-sharing.md); SKILL.md §4 invariants                                                                                                                                 |
| Setup / availability gating                | [availability-and-gating.md](availability-and-gating.md); BE `availability_requirements` note                                                                                                                    |
| Tile layout / mins / add placement         | [layout-and-ux.md](layout-and-ux.md); [architecture.md](architecture.md) if REST/MCP add path changed                                                                                                            |
| WidgetCard / edit modal composition        | [composition.md](composition.md)                                                                                                                                                                                 |
| Tile filter bar / `widgetFilters` config   | [list-widget-patterns.md](list-widget-patterns.md)                                                                                                                                                               |
| List pagination footer / `run_*` totals    | [list-widget-patterns.md](list-widget-patterns.md) (`include_total_count` on dashboard path)                                                                                                                     |
| `run_widgets` rate limits                  | [composition.md](composition.md) or [architecture.md](architecture.md); `widget_query_throttle.py` + product listing throttles (replay)                                                                          |
| Debounced tile refresh after filter PATCH  | `constants.ts` `WIDGET_TILE_REFRESH_DEBOUNCE_MS`; `dashboardLogic.tsx`                                                                                                                                           |
| Header title link / dashboard edit mode    | [list-widget-patterns.md](list-widget-patterns.md); [layout-and-ux.md](layout-and-ux.md) § ⋯ menu parity                                                                                                         |
| MCP tools or agent flows                   | [mcp.md](mcp.md)                                                                                                                                                                                                 |
| New product area / tach / UI reuse pattern | [checklist-new-widget-type.md](checklist-new-widget-type.md) §4c                                                                                                                                                 |
| Human contributor entry point              | [`products/dashboards/CONTRIBUTING.md`](../../../products/dashboards/CONTRIBUTING.md) registry table / Verify block                                                                                              |

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

Run [SKILL.md §6 Verify](../SKILL.md#6-verify) — canonical command list lives there only.

## What not to duplicate

- **Runtime truth** stays in code + tests (`EXPECTED_WIDGET_TYPES`, catalog keys, `registry.test.tsx`). Do not maintain parallel type lists in markdown.
- **Generated files** (`frontend/generated/*`, MCP schema JSON) — regen with `hogli build:openapi`, do not document field-by-field copies.

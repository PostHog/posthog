# Widget config contract and codegen

**When to load:** Pydantic config changes, `hogli build:openapi`, Zod/OpenAPI drift, `ENUM_NAME_OVERRIDES`, or MCP `config_schema` updates.

Platform map (where files live): [architecture.md](architecture.md). Ship checklist: [checklist-new-widget-type.md §1–4](checklist-new-widget-type.md#1-backend-config-contract--registry). Update path: [managing-existing-widgets.md § Config schema migration](managing-existing-widgets.md#config-schema-migration-existing-tiles).

## Config contract (`widget_specs/`)

**Single source of truth for `widget.config` shape** — backend Pydantic models drive runtime validation, REST/MCP OpenAPI, and frontend Zod codegen.

```text
widget_specs/configs.py          Pydantic *WidgetConfig per type (+ shared common.py)
        │
        ├─► pydantic_openapi.py       injects `model_json_schema()` into OpenAPI components (no DRF bridge)
        ├─► openapi.py           polymorphic batch-add / PATCH / catalog OpenAPI (auto from WIDGET_SPECS)
        ├─► registry.py          WIDGET_SPECS manifest + validate_widget_config() (config, catalog labels, run_*)
        └─► widget_catalog.py    config_schema = model_json_schema() (for agents)

bin/build-dashboard-widget-types.py  (hogli build:widget-types — step 1)
        ├─► widget-date-from-options.json   date preset values + labels (from `constants.py`)
        └─► widget-form-fields.json         modal `.pick()` fields (from `WidgetSpec.form_fields`)

generate-widget-config-zod.mjs  (hogli build:widget-types — step 2)
        ├─► widget-config-property-keys.json   per-type keys/trees via `discoverCatalogEntryConfigPropertyKeys()`
        └─► Orval generateReusableSchemas (catalog slice → widget-config-schemas/*.zod.ts)

hogli build:openapi
        ├─► frontend/generated/api.schemas.ts
        ├─► products/dashboards/frontend/generated/widget-configs.zod.ts   (schemas, types, form picks)
        └─► services/mcp/...
```

| File                                | Role                                                                                                                                       |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `configs.py`                        | Per-type Pydantic config models — **edit here first** for field changes                                                                    |
| `common.py`                         | Shared `dateRange`, `widgetFilters`, `filterTestAccounts`                                                                                  |
| `registry.py`                       | `WIDGET_SPECS` + `validate_widget_config()` — per-type manifest (Pydantic model, `run_*`, scopes, RBAC, agent catalog labels/availability) |
| `widgets/config.py`                 | Query-time only — `resolve_filter_test_accounts(config, team)` (validation lives in Pydantic)                                              |
| `openapi.py`                        | Polymorphic OpenAPI for batch-add, catalog `config_schema`, dashboard PATCH — built from `WIDGET_SPECS` (no per-type hand wiring)          |
| `api/widget_openapi_serializers.py` | Stable re-export surface for `dashboard.api` imports (implementation in `widget_specs/openapi.py`)                                         |

**Frontend config layering** (do not duplicate the full schema by hand):

| File                                         | Role                                                                                              |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `generated/widget-config-schemas/*.zod.ts`   | Per-component Orval Zod (`ErrorTrackingListWidgetConfig`, shared `WidgetDateRange`, etc.)         |
| `generated/widget-configs.zod.ts`            | Friendly re-exports, inferred types, form `.pick()` schemas (`hogli build:widget-types`)          |
| `generated/widget-config-property-keys.json` | Per-type top-level config keys from catalog OpenAPI slice (`generate-widget-config-zod.mjs`)      |
| `generated/widget-date-from-options.json`    | Date preset value + label pairs from `constants.py` (`build-dashboard-widget-types.py`)           |
| `generated/widget-form-fields.json`          | Per-widget modal field manifest from `WidgetSpec.form_fields` (`build-dashboard-widget-types.py`) |
| `widgets/widgetConfigValidation.ts`          | Shared HogQL filter helpers + `parseWidgetConfigApiError` — not the per-type schema               |
| `widget_types/widgetConfigShared.ts`         | Re-exports date select options from generated JSON + `resolveWidgetFilterTestAccounts`            |
| `widgets/*/*WidgetConfigValidation.ts`       | Import generated form schema; API error parsing only (colocated with validation)                  |
| `widget_types/catalog.ts`                    | Hand-written: labels, layouts, previews, `defaultConfig` via generated Zod                        |

Copy spine defaults for new types: [widget-intake.md § Defaults](widget-intake.md#defaults-and-inference).

## Codegen & CI

One command — no separate widget codegen step:

```bash
hogli build:openapi   # openapi-schema → build:widget-types → openapi-types → MCP
```

Widget config Zod is product-scoped: `products/dashboards/frontend/bin/generate-widget-config-zod.mjs` slices the catalog op with `filterSchemaByOperationIds` (`dashboards_widget_catalog_retrieve`, `includeResponseSchemas: true`), then runs Orval 8.14+ (`tools/openapi-codegen`) with `generateReusableSchemas: true` into `generated/widget-config-schemas/` and barrels friendly exports in `widget-configs.zod.ts` — separate from `frontend/bin/generate-openapi-types.mjs`. OpenAPI must expose a non-empty `DashboardWidgetConfig` `oneOf` (`pydantic_openapi.py`) or Orval emits an empty union type.

**Local dev:** Vite reads **committed** files under `products/dashboards/frontend/generated/` — no regen on `hogli up` / save. After `widget_specs/` or serializer changes, run `hogli build:openapi` and **commit** the generated diff. No pre-commit hook.

**CI (`check-openapi-types` in `ci-backend.yml`):** runs the same `hogli build:openapi`, then diffs generated outputs. Same-repo PRs may auto-commit drift; fork PRs and unpushed fixes fail with “run `hogli build:openapi` locally”. Triggers on `products/**/backend/**` (incl. `widget_specs/`) and `products/*/frontend/generated/**`.

**New `widget_type`:** add a Pydantic `*WidgetConfig` in `widget_specs/configs.py` following the `*ListWidgetConfig` → `*WidgetConfig` naming convention — `build:widget-types` auto-derives Orval export names and fails if the OpenAPI slice is missing the model.

**Schema gen blocker:** `build:openapi-schema` uses `--fail-on-warn`. Polymorphic per-type OpenAPI serializers each use a singleton `ChoiceField` for `widget_type`; `dashboard.py` uses the full `EXPECTED_WIDGET_TYPES` list — drf-spectacular enum names collide. When shipping a new type, add `{YourWidgetTypeEnum: ["your_widget_type"]}` to `ENUM_NAME_OVERRIDES` in `posthog/settings/web.py` — `hogli build:widget-types` and `test_widget_openapi_enums.py` fail if a registry type lacks an override; spectacular collision test fails if the override hash is wrong. Diagnostic: `python manage.py find_enum_collisions` (logic in `posthog/openapi/enum_collisions.py`). See `/improving-drf-endpoints`.

**Schema parity tests** (cheap drift guards — run when touching `widget_specs/`):

```bash
hogli test products/dashboards/backend/api/test/test_widget_config_schema_parity.py
hogli test products/dashboards/frontend/widgets/widgetConfigSchemaParity.test.ts
```

## Footguns (config / codegen)

| Mistake                                                                | Fix                                                                                                                                                                                                                                                                                                                                                                              |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Slimming `PatchedDashboardOpenApiSerializer` when adding widget fields | `extend_schema(request=...)` **replaces** the whole PATCH schema — extend the class, never rewrite from scratch; CI: `test_dashboard_openapi.py` compares runtime `DashboardSerializer` writables (minus `api/test/dashboard_openapi_test_helpers.py` exclusions) to serializer + spectacular output; MCP test chains `dashboard-update` schema to `DashboardsPartialUpdateBody` |
| Nested per-type widget config serializer on dashboard PATCH            | Keep tile `config` as `JSONField` on runtime serializers — typed OpenAPI lives in `widget_specs/openapi.py` (`PatchedDashboardOpenApiSerializer`) only                                                                                                                                                                                                                           |
| Hand-writing FE Zod config schemas                                     | `widget-configs.zod.ts` from codegen; add Pydantic `*WidgetConfig` + `form_fields` on `WidgetSpec` in `registry.py`                                                                                                                                                                                                                                                              |
| Importing shared `posthog.schema` models into widget config            | Prefer local Pydantic models in `configs.py` (e.g. `WidgetAssigneeFilter`) — avoids OpenAPI component name collisions in spectacular                                                                                                                                                                                                                                             |
| Duplicating catalog `config_schema` by hand                            | BE catalog uses `config_model.model_json_schema()` — agents get bounds/choices/descriptions, not just default values                                                                                                                                                                                                                                                             |
| Editing generated Zod/TS without regen                                 | Run `hogli build:openapi`, commit `products/dashboards/frontend/generated/*` — CI `check-openapi-types` diffs and fails or auto-commits                                                                                                                                                                                                                                          |
| `hogli build:openapi-schema` fails on warnings                         | `--fail-on-warn` — use `find_enum_collisions` + `ENUM_NAME_OVERRIDES`; see [§ Codegen & CI](#codegen--ci)                                                                                                                                                                                                                                                                        |

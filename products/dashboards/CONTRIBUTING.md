# Dashboard widgets

Embeddable dashboard tiles backed by `DashboardWidget` and rendered through the product-local frontend registry in `products/dashboards/frontend/`.

**In scope:** widget tiles (`widget_id` on `DashboardTile`).
**Out of scope:** insight tiles, text cards, and button tiles — separate models today.

Reference implementations: `products/dashboards/frontend/widgets/error_tracking/` (`error_tracking_list`), `products/dashboards/frontend/widgets/session_replay/` (`session_replay_list`).

## Architecture (sketch)

```text
DashboardTile (layout) → widget_id → DashboardWidget (team-scoped)
  widget_type + config  →  WIDGET_REGISTRY (BE)  →  run_widgets
                        →  DASHBOARD_WIDGET_CATALOG + registry.tsx (FE)
```

New `widget_type` strings need **no migration** — register backend + frontend + both catalogs.
Schema changes on `DashboardWidget` / `DashboardTile` use the dashboards migration chain — invoke `django-migrations` when touching those models.

Layer table, registry shapes, copy/move, analytics, and typing details: [`.agents/skills/manage-dashboard-widgets/references/architecture.md`](../../.agents/skills/manage-dashboard-widgets/references/architecture.md)

## Playbook

**Canonical guide:** [`.agents/skills/manage-dashboard-widgets/`](../../.agents/skills/manage-dashboard-widgets/) (`/manage-dashboard-widgets` — ship new types or update shipped types; intake only for new types).

| Task                                | Doc                                                                                                                                |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Add a new widget type               | [`SKILL.md` §2 Ship](../../.agents/skills/manage-dashboard-widgets/SKILL.md#2-ship-a-new-widget_type) → intake, then checklist     |
| First widget in a new product area  | Same — checklist §4c                                                                                                               |
| Update an existing widget type      | [`SKILL.md` §3 Update](../../.agents/skills/manage-dashboard-widgets/SKILL.md#3-update-a-shipped-type) → managing-existing-widgets |
| Tile min/max size on dashboard grid | [`references/layout-and-ux.md`](../../.agents/skills/manage-dashboard-widgets/references/layout-and-ux.md) (§ Tile min/max size)   |
| WidgetCard, loading, headers        | [`references/composition.md`](../../.agents/skills/manage-dashboard-widgets/references/composition.md)                             |
| RBAC, copy/move, shared dashboards  | [`references/permissions-and-sharing.md`](../../.agents/skills/manage-dashboard-widgets/references/permissions-and-sharing.md)     |
| Architecture, naming, scaling rules | [`references/architecture.md`](../../.agents/skills/manage-dashboard-widgets/references/architecture.md)                           |
| MCP / REST                          | [`references/mcp.md`](../../.agents/skills/manage-dashboard-widgets/references/mcp.md)                                             |
| Keep skill docs in sync             | [`references/skill-maintenance.md`](../../.agents/skills/manage-dashboard-widgets/references/skill-maintenance.md)                 |

**Critical rules:**

- Product RBAC is registry-driven — see [permissions-and-sharing.md § Product RBAC](../../.agents/skills/manage-dashboard-widgets/references/permissions-and-sharing.md#product-rbac).
- **Charts/trends on a dashboard → insight tiles**, not new widget types — [architecture.md § Charts](../../.agents/skills/manage-dashboard-widgets/references/architecture.md#charts--use-insight-tiles-not-widgets).

## Frontend / backend parity

Config shape has one SSOT; UI metadata stays hand-written.

| Layer                      | Location                                                              | Hand-written?                                                                                  |
| -------------------------- | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Config contract (Pydantic) | `backend/widget_specs/configs.py`                                     | Yes — edit first                                                                               |
| Runtime validation         | `backend/widget_specs/registry.py` (`validate_widget_config`)         | Derived                                                                                        |
| Registry manifest          | `backend/widget_specs/registry.py` → `EXPECTED_WIDGET_TYPES`          | Per-type `WidgetSpec` entry                                                                    |
| Agent catalog              | `backend/widget_catalog.py` (derived from `WIDGET_SPECS`)             | Labels in `registry.py`; `config_schema` = `model_json_schema()`                               |
| OpenAPI config             | `backend/widget_specs/openapi.py`                                     | Stub DRF serializers + Pydantic `model_json_schema()` via `pydantic_openapi.py` postprocessing |
| FE config Zod              | `frontend/generated/widget-configs.zod.ts` + `widget-config-schemas/` | Codegen — `hogli build:widget-types` (Orval `generateReusableSchemas`)                         |
| FE config property keys    | `frontend/generated/widget-config-property-keys.json`                 | Codegen — `generate-widget-config-zod.mjs` (parity tests)                                      |
| Widget date presets        | `frontend/generated/widget-date-from-options.json`                    | Codegen — `build-dashboard-widget-types.py` (`constants.py` values + labels)                   |
| Widget form field picks    | `frontend/generated/widget-form-fields.json`                          | Codegen — `WidgetSpec.form_fields` in `registry.py`                                            |
| FE UI catalog              | `frontend/widget_types/catalog.ts`                                    | Yes — layouts, previews, copy                                                                  |
| FE runtime registry        | `frontend/widgets/registry.tsx`                                       | Yes — Component, EditModal                                                                     |

See [config-and-codegen.md](../../.agents/skills/manage-dashboard-widgets/references/config-and-codegen.md).

Per-type add flow (ordered): [checklist-new-widget-type.md](../../.agents/skills/manage-dashboard-widgets/references/checklist-new-widget-type.md). Platform invariants: [architecture.md](../../.agents/skills/manage-dashboard-widgets/references/architecture.md).

## Verify

Full command list: [`.agents/skills/manage-dashboard-widgets/SKILL.md` § Verify](../../.agents/skills/manage-dashboard-widgets/SKILL.md#6-verify).

Minimum when adding a type:

```bash
hogli test products/dashboards/backend/api/test/test_run_widgets.py
hogli test products/dashboards/backend/api/test/test_dashboard_widgets.py
hogli test products/dashboards/frontend/widgets/registry.test.tsx
```

After `widget_specs/` changes: `hogli build:openapi` (OpenAPI serializers derive automatically; do not edit `products/dashboards/frontend/generated/`).

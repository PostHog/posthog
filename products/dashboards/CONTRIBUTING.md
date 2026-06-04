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

Layer table, registry shapes, copy/move, analytics, and typing details: [`.agents/skills/dashboard-widgets/references/architecture.md`](../../.agents/skills/dashboard-widgets/references/architecture.md)

## Playbook

**Canonical guide:** [`.agents/skills/dashboard-widgets/`](../../.agents/skills/dashboard-widgets/) (`/dashboard-widgets` — ship new types or update shipped types; intake only for new types).

| Task                                | Doc                                                                                                                         |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Add a new widget type               | [`SKILL.md` §2 Ship](../../.agents/skills/dashboard-widgets/SKILL.md#2-ship-a-new-widget_type) → intake, then checklist     |
| First widget in a new product area  | Same — checklist §4c                                                                                                        |
| Update an existing widget type      | [`SKILL.md` §3 Update](../../.agents/skills/dashboard-widgets/SKILL.md#3-update-a-shipped-type) → managing-existing-widgets |
| Tile min/max size on dashboard grid | [`references/layout-and-ux.md`](../../.agents/skills/dashboard-widgets/references/layout-and-ux.md) (§ Tile min/max size)   |
| WidgetCard, loading, headers        | [`references/composition.md`](../../.agents/skills/dashboard-widgets/references/composition.md)                             |
| RBAC, copy/move, shared dashboards  | [`references/permissions-and-sharing.md`](../../.agents/skills/dashboard-widgets/references/permissions-and-sharing.md)     |
| Architecture, naming, scaling rules | [`references/architecture.md`](../../.agents/skills/dashboard-widgets/references/architecture.md)                           |
| MCP / REST                          | [`references/mcp.md`](../../.agents/skills/dashboard-widgets/references/mcp.md)                                             |
| Keep skill docs in sync             | [`references/skill-maintenance.md`](../../.agents/skills/dashboard-widgets/references/skill-maintenance.md)                 |

**Critical rule:** product RBAC is registry-driven — see [permissions-and-sharing.md § Product RBAC](../../.agents/skills/dashboard-widgets/references/permissions-and-sharing.md#product-rbac).

## Frontend / backend parity

Four registries must stay aligned for every shipped `widget_type`:

| Registry                   | Location                                                                                                            |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `EXPECTED_WIDGET_TYPES`    | `backend/widget_registry.py`                                                                                        |
| `WIDGET_CATALOG`           | `backend/widget_catalog.py`                                                                                         |
| `DASHBOARD_WIDGET_CATALOG` | `frontend/widget_types/catalog.ts`                                                                                  |
| OpenAPI widget config      | `backend/api/widget_openapi_serializers.py` (per-type `*WidgetConfigSerializer` on `_DashboardWidgetConfigOpenApi`) |

Plus FE runtime registry: `DASHBOARD_WIDGET_REGISTRY` in `frontend/widgets/registry.tsx`.

Per-type add flow (ordered): [checklist-new-widget-type.md](../../.agents/skills/dashboard-widgets/references/checklist-new-widget-type.md). Platform invariants: [architecture.md](../../.agents/skills/dashboard-widgets/references/architecture.md).

## Verify

Full command list: [`.agents/skills/dashboard-widgets/SKILL.md` § Verify](../../.agents/skills/dashboard-widgets/SKILL.md#verify).

Minimum when adding a type:

```bash
hogli test products/dashboards/backend/api/test/test_run_widgets.py
hogli test products/dashboards/backend/api/test/test_dashboard_widgets.py
hogli test products/dashboards/frontend/widgets/registry.test.tsx
```

After serializer or `widget_openapi_serializers.py` changes: `hogli build:openapi` (do not edit `products/dashboards/frontend/generated/`).

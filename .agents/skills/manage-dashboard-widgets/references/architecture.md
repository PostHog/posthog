# Dashboard widgets architecture

Platform file map and invariants. **Config/codegen depth:** [config-and-codegen.md](config-and-codegen.md). **List widget UX:** [list-widget-patterns.md](list-widget-patterns.md).

## Mental model

```text
Dashboard
  └── DashboardTile (layout, color, placement)
        └── widget_id → DashboardWidget (team-scoped content entity)
              ├── widget_type: str  # no DB enum — validated in registry/serializer; typed as DashboardWidgetType in Python
              ├── config: JSON
              ├── name, description, audit fields
              └── team FK (tenant isolation)
```

| Layer             | Location                                                                      | Role                                                                                                                 |
| ----------------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Persistence       | `products/dashboards/backend/models/dashboard_widget.py`, `dashboard_tile.py` | Exactly one content FK per tile: insight \| text \| button_tile \| widget (DB CHECK)                                 |
| Backend runtime   | `products/dashboards/backend/widgets/<type>.py` + `widget_specs/registry.py`  | Per-type `run_*`; manifest in `WIDGET_SPECS` (`WidgetSpec`)                                                          |
| Config contract   | `products/dashboards/backend/widget_specs/`                                   | Pydantic SSOT → validation, OpenAPI, Zod — [config-and-codegen.md](config-and-codegen.md)                            |
| Backend access    | `products/dashboards/backend/widget_access.py`                                | `required_product_access` → RBAC check                                                                               |
| Backend catalog   | `products/dashboards/backend/widget_catalog.py`                               | Built from `WIDGET_SPECS`; REST/MCP `config_schema` = Pydantic `model_json_schema()` (bounds, choices, descriptions) |
| Data fetch        | `GET .../dashboards/:id/run_widgets?tile_ids=` in `dashboard.py`              | Batched per-tile results + per-tile errors (generic loop); emits **`dashboard_widget_delivery`** SLO per tile query  |
| Frontend dispatch | `widgets/registry.tsx`                                                        | `DASHBOARD_WIDGET_REGISTRY` → `Component` + `EditModal`                                                              |
| Catalog / layout  | `frontend/widget_types/`                                                      | Add modal, defaults, headers, RBAC map, grid sizing                                                                  |
| Scene glue        | `frontend/src/scenes/dashboard/`                                              | Fetch, CRUD, copy/move, undo remove                                                                                  |

**New `widget_type` strings need no migration** — register in both backend and frontend registries + catalog.

## Naming

| Context                                      | Convention             | Example                                          |
| -------------------------------------------- | ---------------------- | ------------------------------------------------ |
| Product widget dirs under `widgets/`         | `snake_case`           | `widgets/error_tracking/`                        |
| Catalog keys / `widget_type` / registry keys | `snake_case`           | `error_tracking_list`                            |
| Shared `widget_types/` modules               | `snake_case` filenames | `widgetConfigShared.ts`, `widgetAvailability.ts` |
| React component dirs under `components/`     | `PascalCase`           | `WidgetCard/`, `DashboardWidgetItem/`            |
| MCP tool names                               | `kebab-case`           | `dashboard-widgets-run`                          |

Colocate widget code in `widgets/<product>/` — do not scaffold empty `hooks/` or `logic/` dirs until kea is actually needed.

## Shipped types (source of truth)

**Do not hand-maintain type lists in this skill.** Canonical set:

- `EXPECTED_WIDGET_TYPES` / `WIDGET_REGISTRY` — `backend/widget_registry.py` (re-exports `widget_specs/registry.py`; enforced in `test_run_widgets.py` — no separate FE union file)
- `WIDGET_CATALOG` — `backend/widget_catalog.py` (derived from `WIDGET_SPECS`)
- `DASHBOARD_WIDGET_CATALOG` — `frontend/widget_types/catalog.ts` (hand-written UI metadata)
- OpenAPI config serializers — `backend/widget_specs/openapi.py` (derived from `WIDGET_SPECS`; re-exported from `api/widget_openapi_serializers.py`)

CI: `test_run_widgets.py` (registry + catalog + OpenAPI serializer count), `registry.test.tsx` (FE catalog ↔ registry).

## Charts → use insight tiles, not widgets

**Do not ship chart-based widget types** (trends, time series, funnels, breakdowns, pie/bar/line as the primary tile body).

Dashboards already have **insight tiles** for HogQL/query visualizations — comparisons, formulas, breakdowns, subscriptions, and insight-linked alerts. A chart widget duplicates that stack in a smaller tile with worse ergonomics.

| Need on a dashboard                        | Use                                                           |
| ------------------------------------------ | ------------------------------------------------------------- |
| Trend, funnel, retention, stickiness, etc. | Save or build an **insight** → add as a normal dashboard tile |
| Product-native list/table/card context     | **Widget** (`error_tracking_list`, `session_replay_list`, …)  |

If intake is chart-only, **stop** — help the engineer add the right insight to the dashboard instead of a new `widget_type`. Lists may include small non-chart metadata (badges, sparklines in a row) when the product scene does; the tile body is still a list, not a chart canvas.

Per-type add flow (ordered checklist): [checklist-new-widget-type.md](checklist-new-widget-type.md).

## Backend registry entry shape

Files: `products/dashboards/backend/widgets/<widget_type>.py` + `widget_specs/registry.py`

```python
# widgets/your_type.py — run_* only; validation via widget_specs/registry.py
def run_your_type_widget(team, config, user=None, **kwargs) -> dict:
    typed = validate_widget_config(YOUR_TYPE, config)
    ...

# widget_specs/registry.py — WIDGET_SPECS manifest (lazy-imports run_*)
WIDGET_SPECS[YOUR_TYPE] = WidgetSpec(
    widget_type=YOUR_TYPE,
    config_model=YourWidgetConfig,
    query_fn=run_your_type_widget,
    required_scopes=("your_product:read",),
    group_id="your_product",
    group_label="Your product",
    label="Your widget",
    description="Agent-facing catalog copy.",
    required_product_access="your_product",
    product_access_denied_message="You do not have access to your product.",
    availability_requirements=("your_setup_flag",),
)
```

- Config validation is **Pydantic-only** — no per-type `validate_<type>_config` functions
- `run_<type>_widget` lives in `widgets/<widget_type>.py` — call the **same** query runner the standalone product uses
- Registry wiring checklist: [checklist-new-widget-type.md §1–2](checklist-new-widget-type.md)
- Product RBAC: [permissions-and-sharing.md § Product RBAC](permissions-and-sharing.md#product-rbac)

## Frontend registry entry shape

File: `products/dashboards/frontend/widgets/registry.tsx`

```typescript
import { YourWidget } from './your_product/YourWidget'
import { EditYourWidgetModal } from './your_product/EditYourWidgetModal'

export const DASHBOARD_WIDGET_REGISTRY = {
  your_type: {
    Component: YourWidget,
    EditModal: EditYourWidgetModal,
    productAccess: 'your_product',
    parseConfigApiError: parseYourWidgetConfigApiError,
  },
} satisfies Record<DashboardWidgetCatalogKey, DashboardWidgetDefinition>
```

Checklist steps: [checklist-new-widget-type.md §7](checklist-new-widget-type.md#7-frontend-registry).

Catalog entry in `widget_types/catalog.ts` drives add modal, layouts, headers, previews, and **public/shared placeholder copy** — registry alone is not enough.

Optional catalog `availability` declares project setup prerequisites (exception autocapture, etc.). Gating runs at **tile render** via `WidgetRuntimeAvailabilityGuard`, not in the add modal — see [availability-and-gating.md](availability-and-gating.md).

## Widget type vs catalog group

| Field         | Role                                                                                                                                                                                                   |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `widget_type` | Unique ID everywhere: catalog key, `WIDGET_REGISTRY` key, DB column, `DASHBOARD_WIDGET_REGISTRY` key                                                                                                   |
| `groupId`     | Product area section in add-widget modal — **multiple `widget_type` entries can share one group** (e.g. `error_tracking_list` and another error-tracking variant both use `groupId: 'error_tracking'`) |
| `label`       | Variant name within the group ("Top issues", "Recent recordings"); fallback card title                                                                                                                 |

Group display labels live in `DASHBOARD_WIDGET_GROUP_LABELS` — use `getDashboardWidgetGroupLabel(groupId)` in edit modals and card headers.

`getDashboardWidgetCatalogGroups()` in `AddWidgetModal.tsx` builds grouped picker sections from catalog entries. Card headers use `getDashboardWidgetGroupLabel(groupId)` for the product type chip (`DashboardWidgetItem` → `WidgetCardHeader`).

Adding a second variant in an existing group still requires a full new `widget_type` stack — only `groupId` is reused. See checklist §4b.

## Platform files — do not branch per type

| File                             | Role                                                                                                                  |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `dashboard.py` `run_widgets`     | Generic loop — `get_widget_registry_entry` + `get_widget_product_access_error` only                                   |
| `DashboardWidgetItem.tsx`        | Generic shell — RBAC via `userHasDashboardWidgetProductAccess`; unknown types: header fallback + body `ErrorBoundary` |
| `WidgetCard.tsx` / header / body | Shared compound chrome — no product imports                                                                           |
| `dashboardLogic.tsx`             | Generic fetch/CRUD — no `widget_type` switches for data                                                               |
| `widgetFetchUtils.ts`            | Batched `run_widgets` only                                                                                            |

Import `Component` / `EditModal` directly in `registry.tsx` (no `React.lazy`). Each new type adds files under `backend/widgets/` and `frontend/widgets/<product>/` — not branches in the table above.

## CI type-safety nets

- **OpenAPI drift:** [config-and-codegen.md § Codegen & CI](config-and-codegen.md#codegen--ci)
- BE: `EXPECTED_WIDGET_TYPES == WIDGET_REGISTRY.keys()` and `WIDGET_CATALOG` keys match
- BE: OpenAPI polymorphic config serializer count matches registry (`test_run_widgets.py`)
- BE: catalog `config_schema` matches Pydantic JSON schema (`test_widget_config_schema_parity.py`)
- BE: per-type `widget_type` enum overrides (`test_widget_openapi_enums.py`; `build:widget-types` preflight)
- BE: dashboard PATCH OpenAPI ⊆ runtime writables (`test_dashboard_openapi.py` + `api/test/dashboard_openapi_test_helpers.py`)
- FE: `DASHBOARD_WIDGET_REGISTRY satisfies Record<DashboardWidgetCatalogKey, …>`
- FE: `DASHBOARD_WIDGET_PREVIEWS` keyed by catalog; `registry.test.tsx` covers every catalog key
- FE: Zod config top-level keys match backend property map (`widgetConfigSchemaParity.test.ts` + `widget-config-property-keys.json`)
- Runtime: `getDashboardWidgetDefinition` → PostHog `captureException` on miss (deploy skew)

## Footguns

| Mistake                                | Fix                                                                                                                                                                    |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Config / OpenAPI / Zod mistakes        | [config-and-codegen.md § Footguns](config-and-codegen.md#footguns-config--codegen)                                                                                     |
| Registry entry without catalog entry   | Catalog drives add modal, layouts, headers, previews — registry alone is not enough                                                                                    |
| Reused `widget_type` for a new variant | Each variant needs its own catalog key + full BE/FE stack; share `groupId` only                                                                                        |
| `gridChildren` used for widget body    | RGL resize handles only — content goes in composed `WidgetCardBody`                                                                                                    |
| Config API error parsing in `utils.ts` | Per-type **`parseConfigApiError`** on `DASHBOARD_WIDGET_REGISTRY` entry                                                                                                |
| Export vs public/shared confused       | Export hides widget tiles; public/shared render **`WidgetCardSharedPlaceholderBody`** without `run_widgets` — [permissions-and-sharing.md](permissions-and-sharing.md) |

Easy-to-miss paths when adding a type: `backend/widget_layouts.py` (batch-add placement), `posthog/models/resource_transfer/visitors/dashboard_widget.py` (cross-project copy), `posthog/api/test/test_sharing.py` (shared payload).

## Scene integration (usually no changes for new types)

Only touch when the new type needs special fetch/CRUD behavior:

| File                         | Widget-related behavior                                                                                                                                                                                                   |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dashboardLogic.tsx`         | `addWidgetTiles` (batch POST `.../widgets/batch/`), `refreshDashboardWidgets`, `updateWidgetTile`, `widgetResultsByTileId`, `dashboardWidgetsEnabled`, copy/move — **skips `run_widgets` on `DashboardPlacement.Public`** |
| `DashboardItems.tsx`         | Renders `DashboardWidgetItem` when `dashboardWidgetsEnabled && isWidgetTileVisibleOnPlacement` (export hides widgets; public renders placeholders)                                                                        |
| `DashboardHeaderActions.tsx` | Add widget entry                                                                                                                                                                                                          |
| `DashboardModals.tsx`        | `AddWidgetModal` (multi-select)                                                                                                                                                                                           |
| `tileLayouts.ts`             | Widget default/min layout from catalog                                                                                                                                                                                    |
| `widgetFetchUtils.ts`        | Batched `run_widgets` fetch (15 min client TTL)                                                                                                                                                                           |
| `dashboardUtils.ts`          | `getDashboardWidgetType`, `isWidgetTileVisibleOnPlacement` (export-only hide), template helpers                                                                                                                           |

## Add widget flows

| Surface        | Mechanism                                                                                                                                                            |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| UI add modal   | `AddWidgetModal` multi-select → `addWidgetTiles` → POST `.../dashboards/:id/widgets/batch/`                                                                          |
| REST / MCP add | `POST .../dashboards/:id/widgets/batch/` — 1–10 tiles. New tiles land on the **bottom row** via `widget_layouts.stack_widget_layout_at_bottom`. See [mcp.md](mcp.md) |

## Analytics

First-time widget tile insert fires server-side events via `_report_dashboard_tile_added` in `dashboard.py`:

- **`dashboard tile added`** — generic tile event with `tile_type: "widget"`, `widget_type`, `dashboard_id`
- **`dashboard widget added`** — widget-specific event with `widget_type`, `dashboard_id`, `tile_id`, `widget_id`, plus request `source` (`web` | `mcp` | `api` | …) from `report_user_action`

Both fire on:

- PATCH dashboard `tiles[]` with a new widget tile (tests / legacy harness)
- POST `.../widgets/batch/` (UI `addWidgetTiles`, REST, MCP)

Config/metadata updates do not re-fire either event.

## Delivery SLO

Each successful/failed widget query in `_run_widget_query` emits **`dashboard_widget_delivery`** via `slo_operation` (`SloArea.ANALYTIC_PLATFORM`) with `widget_type`, `dashboard_id`, and `tile_id`. No per-type SLO wiring — shipping a new registry entry is enough. Access/validation failures before `query_fn` runs do not emit this SLO.

## Copy, move, duplicate

Cross-project transfer, cross-dashboard copy/move, and dashboard duplication all deep-clone widget rows (move reassigns the tile only). Details: [permissions-and-sharing.md](permissions-and-sharing.md).

## Reference implementation

Mirror `products/dashboards/frontend/widgets/error_tracking/` (`error_tracking_list`). Replay pattern: `widgets/session_replay/` — see [widget-intake.md § Defaults](widget-intake.md#defaults-and-inference).

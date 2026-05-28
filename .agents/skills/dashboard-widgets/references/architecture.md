# Dashboard widgets architecture

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

| Layer | Location | Role |
| ----- | -------- | ---- |
| Persistence | `products/dashboards/backend/models/dashboard_widget.py`, `dashboard_tile.py` | Exactly one content FK per tile: insight \| text \| button_tile \| widget (DB CHECK) |
| Backend runtime | `products/dashboards/backend/widgets/<type>.py` + `widget_registry.py` | Per-type validate/run; aggregator registry |
| Backend access | `products/dashboards/backend/widget_access.py` | `required_product_access` → RBAC check |
| Backend catalog | `products/dashboards/backend/widget_catalog.py` | Labels, grouping, `config_schema_hints` for REST/MCP |
| Data fetch | `GET .../dashboards/:id/run_widgets?tile_ids=` in `dashboard.py` | Batched per-tile results + per-tile errors (generic loop) |
| Frontend dispatch | `widgets/registry.tsx` | `DASHBOARD_WIDGET_REGISTRY` → `Component` + `EditModal` |
| Catalog / layout | `frontend/widget_types/` | Add modal, defaults, headers, RBAC map, grid sizing |
| Scene glue | `frontend/src/scenes/dashboard/` | Fetch, CRUD, copy/move, undo remove |

**New `widget_type` strings need no migration** — register in both backend and frontend registries + catalog.

## Backend registry entry shape

Files: `products/dashboards/backend/widgets/<widget_type>.py` + `widget_registry.py`

```python
# widgets/your_type.py — validate + run for one widget_type
# widget_registry.py — aggregator only
WIDGET_REGISTRY: dict[str, WidgetRegistryEntry] = {
    "your_type": {
        "validate_config": validate_your_type_config,
        "query_fn": run_your_type_widget,
        "required_scopes": ["your_product:read"],  # documentation only
        "required_product_access": "your_product",  # RBAC gate via widget_access.py
    },
}
```

- `validate_<type>_config` / `run_<type>_widget` live in `widgets/<widget_type>.py` — call the **same** query runner the standalone product uses
- `required_product_access` drives `get_widget_product_access_error` in `run_widgets` and tile mutations — do not add per-type checks in `dashboard.py`
- Add type to `EXPECTED_WIDGET_TYPES` (must equal `WIDGET_REGISTRY.keys()` — enforced in tests)
- Extend `DashboardWidgetType` (`Literal[...]`) — canonical types only; used in typed Python call sites
- Extend `DashboardWidgetTypeInput` when API/tests accept alternate type aliases (`WIDGET_TYPE_ALIASES`)
- Shared date-range validation: `widgets.config.validate_widget_date_range`

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
    },
} satisfies Record<DashboardWidgetCatalogKey, DashboardWidgetDefinition>
```

Catalog entry in `widget_types/catalog.ts` drives add modal, layouts, headers, and previews — registry alone is not enough.

Optional catalog `availability` declares project setup prerequisites (exception autocapture, etc.). Gating runs at **tile render** via `WidgetRuntimeAvailabilityGuard`, not in the add modal — see [availability-and-gating.md](availability-and-gating.md).

## Widget type vs catalog group

| Field | Role |
| ----- | ---- |
| `widget_type` | Unique ID everywhere: catalog key, `WIDGET_REGISTRY` key, DB column, `DASHBOARD_WIDGET_REGISTRY` key |
| `groupId` / `groupLabel` | Product area section in add-widget modal — **multiple `widget_type` entries share one group** (e.g. `error_tracking_list` + a future `error_tracking_<variant>` both use `groupId: 'error_tracking'`, `groupLabel: 'Error tracking'`) |
| `label` | Variant name within the group ("Top issues", "Trend chart"); fallback card title |

`getDashboardWidgetCatalogGroups()` in `AddWidgetModal.tsx` builds grouped picker sections from catalog entries. Card headers use `groupLabel` for the product type chip (`DashboardWidgetItem` → `WidgetCardHeader`).

Adding a second variant in an existing group still requires a full new `widget_type` stack — only `groupId`/`groupLabel` are reused. See checklist §4b and [scaling.md](scaling.md).

## Scaling

Many widget types: platform glue stays generic; each type adds product-local files. See [scaling.md](scaling.md).

## Scene integration (usually no changes for new types)

Only touch when the new type needs special fetch/CRUD behavior:

| File | Widget-related behavior |
| ---- | ----------------------- |
| `dashboardLogic.tsx` | `addWidgetTiles` (multi-tile add via dashboard PATCH), `refreshDashboardWidgets`, `updateWidgetTileConfig`, `widgetResultsByTileId`, `dashboardWidgetsEnabled`, copy/move |
| `DashboardItems.tsx` | Renders `DashboardWidgetItem`; passes refresh/results |
| `DashboardHeaderActions.tsx` | Add widget entry |
| `DashboardModals.tsx` | `AddWidgetModal` (multi-select) |
| `tileLayouts.ts` | Widget default/min layout from catalog |
| `widgetFetchUtils.ts` | Batched `run_widgets` fetch (15 min client TTL) |
| `dashboardUtils.ts` | `getDashboardWidgetType`, template helpers |

## Add widget flows

| Surface | Mechanism |
| ------- | --------- |
| UI add modal | `AddWidgetModal` multi-select → `addWidgetTiles` → PATCH dashboard with multiple new tile payloads |
| REST / MCP single add | `POST .../dashboards/:id/widgets/` — one tile (`widget_type` + `config`). See [mcp.md](mcp.md) |

## Analytics

First-time widget tile insert fires `dashboard tile added` with `tile_type: "widget"`, `widget_type`, and `dashboard_id` via `_report_dashboard_tile_added` in `dashboard.py`:

- PATCH dashboard `tiles[]` (UI `addWidgetTiles`)
- POST `.../widgets/` (REST/MCP)

Config updates do not re-fire the event.

## Copy, move, duplicate

Cross-project transfer, cross-dashboard copy/move, and dashboard duplication all deep-clone widget rows (move reassigns the tile only). Details: [permissions-and-sharing.md](permissions-and-sharing.md).

## Reference implementation

Mirror `products/dashboards/frontend/widgets/error_tracking/` for end-to-end patterns.

# Permissions and sharing

## Team scoping

- `DashboardWidget.team` required — all reads/writes filter by `team_id`
- Tile upsert validates existing widget IDs belong to the dashboard's team

## Two access layers (both must pass)

| Layer          | Check                                                                                      |
| -------------- | ------------------------------------------------------------------------------------------ |
| Dashboard RBAC | `dashboard:read` / `dashboard:write`; access level on dashboard object                     |
| Product RBAC   | See [Product RBAC](#product-rbac) below — frontend lock + backend `run_widgets` must agree |

## Product RBAC

Canonical rule (also SKILL.md rule 1):

- Backend: `required_product_access` on each `WidgetSpec` in `registry.py` (surfaced via `WIDGET_REGISTRY` / `get_widget_registry_entry`) → `get_widget_product_access_error` in `widget_access.py` for `run_widgets` and tile mutations
- Frontend: matching `productAccess` on catalog + registry; `userHasDashboardWidgetProductAccess` in `DashboardWidgetItem.tsx`; extend `DashboardWidgetProductAccess` and `WIDGET_PRODUCT_ACCESS_CHECKS` when adding a gated product
- **`required_scopes` on registry entries is documentation only** — never use it for enforcement
- **Never** add per-type `if widget_type == …` in `dashboard.py`

**Frontend `locked` alone is insufficient** — backend must enforce the same gate.

**Error tracking list tile** — row status/assignee mutations: dashboard edit **or** Error tracking Editor (`userCanMutateErrorTrackingIssuesOnDashboard` in `widgetProductAccess.ts`). Tile filter PATCH still needs dashboard edit.

## Copy / move / duplicate

| Action                          | Widget support                                                                                                                               |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Duplicate within same dashboard | Deep-clones widget row; `duplicateTileSuccess` triggers `refreshDashboardWidgets` for the new tile so data loads without a full page refresh |
| Copy to another dashboard       | Deep-clones widget row + tile on destination (name gets `(Copy)` when set)                                                                   |
| Move to another dashboard       | Moves tile row; same `DashboardWidget` FK (widgets are not shared across dashboards)                                                         |
| Duplicate entire dashboard      | Always deep-clones widget rows (even when `duplicate_tiles: false` for insights)                                                             |

Button tiles still cannot be copied or moved between dashboards.

## Cross-project copy

Transferring a dashboard between projects deep-clones widget rows. `DashboardWidgetVisitor` (`posthog/models/resource_transfer/visitors/dashboard_widget.py`) is `user_facing=True` (default) so widgets appear in transfer preview dependencies with `display_name` from widget `name` when set. `DashboardTile` visitor stays `user_facing=False`. Tests: `posthog/api/test/test_resource_transfer.py` (`test_preview_returns_dashboard_with_widget_tiles`).

## Shared / public / subscriptions

| Placement                                              | Widget tile behavior                                                                                                                                |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Private dashboard                                      | Full tile: `run_widgets` fetch, live `Component`, edit chrome when allowed                                                                          |
| **Public / shared link** (`DashboardPlacement.Public`) | Tile **renders** with header metadata; **no** `run_widgets` fetch; body shows catalog **`sharedPlaceholder`** via `WidgetCardSharedPlaceholderBody` |
| Export (`DashboardPlacement.Export`)                   | Widget tiles **hidden** (`isWidgetTileVisibleOnPlacement` — export only)                                                                            |
| Subscriptions / snapshots                              | Read-only — no edit modal, no mutations from tile chrome                                                                                            |

### Public shared dashboards (implementation)

- **`isWidgetTileVisibleOnPlacement`** (`dashboardUtils.ts`) — hides widgets on **export** only; public/shared still render tiles
- **`dashboardLogic.dashboardWidgetsEnabled`** — `true` on public when the dashboard has widget tiles (enables tile chrome + layout; still skips `refreshDashboardWidgets` when `placement === Public`)
- **`SharedDashboardWidgetMetadataSerializer`** (`dashboard.py`) — when tile serializer context has `is_shared`, widget payload is metadata-only (no audit/user fields beyond what the shared view needs)
- **Sharing path** — `posthog/api/sharing.py` sets `is_shared: True` on dashboard tile serializer context
- **Frontend placeholder** — `DashboardWidgetItem` branches on `placement === Public` → `WidgetCardSharedPlaceholderBody` with `headerCatalogEntry.sharedPlaceholder ?? DEFAULT_SHARED_DASHBOARD_WIDGET_PLACEHOLDER` from `catalog.ts`
- **`titleHref`** suppressed on public; ⋯ menu / edit controls hidden via existing placement helpers
- **Tests** — `posthog/api/test/test_sharing.py` (widget tiles in shared payload); `DashboardWidgetItem.test.tsx` (public placeholder)

When adding a type, set **`sharedPlaceholder`** `{ title, message }` on the catalog entry (product-specific copy). Omit only if generic fallback copy is acceptable.

## Activity logging

- `DashboardWidget` uses `ModelActivityMixin`; scope `"DashboardWidget"`
- `handle_dashboard_widget_change` in `dashboard.py` logs create/update/delete
- Do not store secrets in `config` — changes are logged

# Permissions and sharing

## Team scoping

- `DashboardWidget.team` required — all reads/writes filter by `team_id`
- Tile upsert validates existing widget IDs belong to the dashboard's team

## Two access layers (both must pass)

| Layer | Check |
| ----- | ----- |
| Dashboard RBAC | `dashboard:read` / `dashboard:write`; access level on dashboard object |
| Product RBAC | Can user see the underlying data? Frontend: `userHasDashboardWidgetProductAccess(definition.productAccess)` in `DashboardWidgetItem`. Backend: `required_product_access` on `WIDGET_REGISTRY` → `get_widget_product_access_error` in `run_widgets` and tile mutations |

**Frontend `locked` alone is insufficient** — set `required_product_access` on the registry entry so backend enforces the same gate.

## Copy / move / duplicate

| Action | Widget support |
| ------ | -------------- |
| Duplicate within same dashboard | Deep-clones widget row |
| Copy to another dashboard | Deep-clones widget row + tile on destination (name gets ` (Copy)` when set) |
| Move to another dashboard | Moves tile row; same `DashboardWidget` FK (widgets are not shared across dashboards) |
| Duplicate entire dashboard | Always deep-clones widget rows (even when `duplicate_tiles: false` for insights) |

Button tiles still cannot be copied or moved between dashboards.

## Cross-project copy

Transferring a dashboard between projects deep-clones widget rows. `DashboardWidgetVisitor` (`posthog/models/resource_transfer/visitors/dashboard_widget.py`) is `user_facing=True` (default) so widgets appear in transfer preview dependencies with `display_name` from widget `name` when set. `DashboardTile` visitor stays `user_facing=False`. Tests: `posthog/api/test/test_resource_transfer.py` (`test_preview_returns_dashboard_with_widget_tiles`).

## Shared / public / subscriptions

- `placement === DashboardPlacement.Public` hides edit controls and ⋯ menu
- `titleHref` suppressed on public dashboards
- Widget tiles are not rendered on shared/public/export placements (`isWidgetTileVisibleOnPlacement` in `DashboardItems.tsx`)
- Subscriptions and snapshots render read-only — no edit modal, no mutations from tile chrome

## Activity logging

- `DashboardWidget` uses `ModelActivityMixin`; scope `"DashboardWidget"`
- `handle_dashboard_widget_change` in `dashboard.py` logs create/update/delete
- Do not store secrets in `config` — changes are logged

## `required_scopes` and `required_product_access`

`required_scopes` on `WIDGET_REGISTRY` entries is documentation only. RBAC is driven by `required_product_access` — `widget_access.get_widget_product_access_error` handles `run_widgets` and tile mutations. Do not add per-type checks in `dashboard.py`.

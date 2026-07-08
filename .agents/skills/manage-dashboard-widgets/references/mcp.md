# Dashboard widgets MCP tools

Agents manage dashboard widget tiles through atomic MCP tools.

Tool config: `products/dashboards/mcp/tools.yaml` — regenerate MCP handlers after endpoint changes (`implementing-mcp-tools` skill).

## Tool map

| Goal                                  | MCP tool                              | Notes                                                                                          |
| ------------------------------------- | ------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Discover widget types + config schema | `dashboard-widget-catalog-list`       | Read-only catalog; per-type `config_schema` = Pydantic JSON schema (bounds, choices, defaults) |
| Read dashboard tiles + widget config  | `dashboard-get`                       | Widget tiles have `widget.widget_type` and `widget.config`; no live data                       |
| Add widget tile(s)                    | `dashboard-widgets-batch-add`         | Atomic batch via `POST .../widgets/batch/` (1–10 tiles; one tile = single-element `widgets`)   |
| Update widget tile(s)                 | `dashboard-update`                    | PATCH dashboard with `tiles[]`: each tile `id` + `widget.id` + fields to change                |
| Run widget queries                    | `dashboard-widgets-run`               | Query: `tile_ids` comma-separated from dashboard-get                                           |
| Copy widget tile to another dashboard | `dashboard-tile-copy`                 | Deep-clones widget; destination is path dashboard ID                                           |
| Move widget tile between dashboards   | `dashboards-move-tile-partial-update` | Source dashboard is path `id`; pass `to_dashboard` and `tile.id` from dashboard-get            |

There is no dedicated single-tile create or per-tile `PATCH .../widgets/:tile_id/` REST endpoint — the UI and MCP use batch add and dashboard PATCH respectively.

## Typical agent flow

1. `dashboard-widget-catalog-list` — pick `widget_type`, build `config` from `config_schema` (same shape as batch-add / PATCH OpenAPI; includes `widgetFilters` when supported)
2. `dashboard-widgets-batch-add` — add one or more tiles (up to 10 per request)
3. `dashboard-get` — confirm tile ID(s), widget row `id`, and layout
4. `dashboard-widgets-run` — fetch live widget data for `tile_ids` (private dashboards only — public/shared views do not call `run_widgets`)

For updates: `dashboard-update` with `tiles` containing `{ id, widget: { id, config?, name?, description? } }`, then `dashboard-widgets-run` when live data should refresh.

Multi-tile add from the UI uses `POST .../widgets/batch/` (`addWidgetTiles`), same as MCP batch add.

## REST equivalents

| MCP tool                              | Endpoint                                                      |
| ------------------------------------- | ------------------------------------------------------------- |
| `dashboard-widget-catalog-list`       | `GET .../dashboards/widget_catalog/`                          |
| `dashboard-widgets-batch-add`         | `POST .../dashboards/:id/widgets/batch/` (1–10 tiles, atomic) |
| `dashboard-update` (widget tiles)     | `PATCH .../dashboards/:id` with `tiles[]` and nested `widget` |
| `dashboard-widgets-run`               | `GET .../dashboards/:id/run_widgets/?tile_ids=`               |
| `dashboard-tile-copy`                 | `POST .../dashboards/:id/copy_tile/`                          |
| `dashboards-move-tile-partial-update` | `PATCH .../dashboards/:id/move_tile/`                         |

UI multi-select add uses `POST .../widgets/batch/` (not PATCH dashboard `tiles[]` for create).

## Permissions

- Dashboard edit scope for add/update/copy/move
- Dashboard read scope for get, catalog, run
- Each widget type may require additional product access — check `required_product_access` on `dashboard-widget-catalog-list`; denied tiles return per-tile errors from run/add paths

## After shipping a new `widget_type`

1. Regenerate OpenAPI (`hogli build:openapi`) — updates MCP tool schemas that embed supported type lists
2. Run `hogli test services/mcp/tests/tools/dashboards.integration.test.ts`
3. Update unit schema snapshots if batch-add help text lists types: `hogli test services/mcp/tests/unit/tool-schema-snapshots.test.ts`

# Dashboard widgets MCP tools

Agents manage dashboard widget tiles through atomic MCP tools.

Tool config: `products/dashboards/mcp/tools.yaml` — regenerate MCP handlers after endpoint changes (`implementing-mcp-tools` skill).

## Tool map

| Goal                                  | MCP tool                              | Notes                                                                                              |
| ------------------------------------- | ------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Discover widget types + config schema | `dashboard-widget-catalog-list`       | Read-only catalog; per-type `config_schema` = Pydantic JSON schema (bounds, choices, defaults)     |
| Read dashboard tiles + widget config  | `dashboard-get`                       | Widget tiles have `widget.widget_type` and `widget.config`; no live data                           |
| Add widget tile(s)                    | `dashboard-widgets-batch-add`         | Atomic batch via `POST .../widgets/batch/` (1–10 tiles; one tile = single-element `widgets`)       |
| Update widget tile(s)                 | `dashboard-widgets-batch-update`      | Atomic batch (1–10): each entry `tile_id` + the fields to change (`config`, `name`, `description`) |
| Resize or move widget tile(s)         | `dashboard-update`                    | PATCH dashboard with `tiles[]`: each tile `id` + `layouts`; it does not change widget settings     |
| Run widget queries                    | `dashboard-widgets-run`               | Query: `tile_ids` comma-separated from dashboard-get                                               |
| Copy widget tile to another dashboard | `dashboard-tile-copy`                 | Deep-clones widget; destination is path dashboard ID                                               |
| Move widget tile between dashboards   | `dashboards-move-tile-partial-update` | Source dashboard is path `id`; pass `to_dashboard` and `tile.id` from dashboard-get                |

There is no dedicated single-tile create or per-tile `PATCH .../widgets/:tile_id/` REST endpoint. MCP uses the batch endpoints for both. The UI adds with the batch endpoint and edits widget settings through the dashboard PATCH with a nested `widget`, which the `dashboard-update` MCP tool does not expose.

## Typical agent flow

1. `dashboard-widget-catalog-list` — pick `widget_type`, build `config` from `config_schema` (the batch tool schemas do not list config keys, so read them here; includes `widgetFilters` when supported)
2. `dashboard-widgets-batch-add` — add one or more tiles (up to 10 per request)
3. `dashboard-get` — confirm tile ID(s), widget row `id`, and layout
4. `dashboard-widgets-run` — fetch live widget data for `tile_ids` (private dashboards only — public/shared views do not call `run_widgets`)

For updates: `dashboard-widgets-batch-update` with `widgets` containing `{ tile_id, config?, name?, description? }`, then `dashboard-widgets-run` when live data should refresh. A `config` update merges into the stored config.

Multi-tile add from the UI uses `POST .../widgets/batch/` (`addWidgetTiles`), same as MCP batch add.

## REST equivalents

| MCP tool                              | Endpoint                                                      |
| ------------------------------------- | ------------------------------------------------------------- |
| `dashboard-widget-catalog-list`       | `GET .../dashboards/widget_catalog/`                          |
| `dashboard-widgets-batch-add`         | `POST .../dashboards/:id/widgets/batch/` (1–10 tiles, atomic) |
| `dashboard-widgets-batch-update`      | `PATCH .../dashboards/:id/widgets/batch_update/`              |
| `dashboard-update` (tile layout)      | `PATCH .../dashboards/:id` with `tiles[]` and `layouts`       |
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
4. To check that agents can configure the new type, add a case to `products/dashboards/evals/eval_dashboard_widgets.py` and run `hogli evals eval_dashboard_widgets` (see the `writing-evals` skill)

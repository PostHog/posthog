# Dashboard widgets MCP tools

Agents manage dashboard widget tiles through atomic MCP tools.

Tool config: `products/dashboards/mcp/tools.yaml` — regenerate MCP handlers after endpoint changes (`implementing-mcp-tools` skill).

## Tool map

| Goal | MCP tool | Notes |
| ---- | -------- | ----- |
| Discover widget types + config hints | `dashboard-widget-catalog-list` | Read-only catalog |
| Read dashboard tiles + widget config | `dashboard-get` | Widget tiles have `widget.widget_type` and `widget.config`; no live data |
| Add widget tile | `dashboard-widget-add` | Single tile via `POST .../widgets/` |
| Add multiple widget tiles | `dashboard-widgets-batch-add` | Atomic batch via `POST .../widgets/batch/` |
| Update widget tile | `dashboard-widget-update` | Path: dashboard ID + `tile_id` from dashboard-get |
| Run widget queries | `dashboard-widgets-run` | Query: `tile_ids` comma-separated from dashboard-get |
| Copy widget tile to another dashboard | `dashboard-tile-copy` | Deep-clones widget; destination is path dashboard ID |
| Move widget tile between dashboards | `dashboards-move-tile-partial-update` | Reassigns tile row; source is path dashboard ID |

## Typical agent flow

1. `dashboard-widget-catalog-list` — pick `widget_type`, build `config` from `config_schema_hints`
2. `dashboard-widget-add` or `dashboard-widgets-batch-add` — add one tile or up to 10 atomically
3. `dashboard-get` — confirm tile ID(s) and layout
4. `dashboard-widgets-run` — fetch live widget data for `tile_ids`

For updates: `dashboard-widget-update` then `dashboard-widgets-run`.

Multi-tile add from the UI uses `POST .../widgets/batch/` (`addWidgetTiles`), same as MCP batch add.

## REST equivalents

| MCP tool | Endpoint |
| -------- | -------- |
| `dashboard-widget-catalog-list` | `GET .../dashboards/widget_catalog/` |
| `dashboard-widget-add` | `POST .../dashboards/:id/widgets/` (single tile) |
| `dashboard-widgets-batch-add` | `POST .../dashboards/:id/widgets/batch/` (1–10 tiles, atomic) |
| `dashboard-widget-update` | `PATCH .../dashboards/:id/widgets/:tile_id/` |
| `dashboard-widgets-run` | `GET .../dashboards/:id/run_widgets/?tile_ids=` |
| `dashboard-tile-copy` | `POST .../dashboards/:id/copy_tile/` |
| `dashboards-move-tile-partial-update` | `PATCH .../dashboards/:id/move_tile/` |

UI multi-select add uses `POST .../widgets/batch/` (not PATCH dashboard `tiles[]`).

## Permissions

- Dashboard edit scope for add/update/copy/move
- Dashboard read scope for get, catalog, run
- Each widget type may require additional product access — check `required_product_access` on `dashboard-widget-catalog-list`; denied tiles return per-tile errors from run/add/update paths

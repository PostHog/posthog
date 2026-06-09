# Layout and UX

## Grid sizing (overview)

Catalog `defaultLayout` drives default size and resize floors via `tileLayouts.ts`. Wide tables scroll inside `WidgetCardContent`, not the dashboard grid.

**Tile min/max size (the full guide):** [§ Tile min/max size](#tile-minmax-size-grid-rows--columns) below — only authoritative section for mins; other docs should link here.

## Tile min/max size (grid rows & columns)

Changing minimum tile size is **catalog + `tileLayouts.ts`**, not the widget `Component`. Agents often look in the wrong layer first — use this section.

### Mental model

```text
DASHBOARD_WIDGET_CATALOG[].defaultLayout     ← you edit this
        ↓
tileLayouts.ts :: calculateLayouts()         ← reads catalog per tile.widget.widget_type
        ↓
react-grid-layout minW / minH on each item   ← enforced while resizing in edit mode
```

- Grid is **12 columns** wide (`w` / `minW` are column counts).
- Height is in **row units** (`h` / `minH`), not columns — users may say “3 rows tall” or “3 grid rows”.
- **Row height:** `BASE_ROW_HEIGHT = 80` px in `frontend/src/scenes/dashboard/DashboardItems.tsx`. Example: `minH: 3` → 240 px minimum tile height (plus margins).

### Single source of truth

Set mins on the catalog entry only:

```typescript
// products/dashboards/frontend/widget_types/catalog.ts
defaultLayout: { w: 6, h: 5, minW: 6, minH: 3 },
```

| Field          | Meaning                                                                             |
| -------------- | ----------------------------------------------------------------------------------- |
| `w`, `h`       | Default size when **adding** a widget (`dashboardLogic.addWidgetTiles` reads these) |
| `minW`, `minH` | Smallest size allowed when **resizing** on the dashboard                            |

### How mins reach the grid

1. `calculateLayouts(tiles)` in `frontend/src/scenes/dashboard/tileLayouts.ts` runs on every dashboard load / tile change.
2. For widget tiles it calls `getWidgetCatalogLayout(widget_type)` → `DASHBOARD_WIDGET_CATALOG[key].defaultLayout`.
3. `getTileMinDimensions()` sets RGL `minW` / `minH` on each layout item.

**Persisted tile JSON** (`tile.layouts.sm`) stores `x`, `y`, `w`, `h` — not mins. Mins are **recomputed** from catalog each time, so a catalog `minH` change applies to existing dashboards without a migration.

### Fallbacks (when catalog omits mins)

| Constant                      | Value | Used when                          |
| ----------------------------- | ----- | ---------------------------------- |
| `MIN_WIDGET_TILE_WIDTH_COLS`  | 6     | Widget tile, catalog has no `minW` |
| `MIN_WIDGET_TILE_HEIGHT_ROWS` | 4     | Widget tile, catalog has no `minH` |
| `MIN_TILE_HEIGHT_ROWS`        | 2     | Insight tiles                      |
| `MIN_TEXT_TILE_HEIGHT_ROWS`   | 1     | Text tiles                         |

If a new widget type omits `minH`, users can only shrink to **4 rows**, not 3. Always set explicit `minH` / `minW` on the catalog entry.

### What does **not** control dashboard min size

| Location                                           | Why it’s unrelated                                                    |
| -------------------------------------------------- | --------------------------------------------------------------------- |
| Widget `Component` / SCSS                          | Body layout only; RGL sizes the outer tile                            |
| `widget_catalog.py` `get_default_widget_layouts()` | Backend add helper — returns `w`/`h` only, no mins                    |
| Storybook `widgetCardStoryFixtures` `TILE_HEIGHT`  | Fixed frame for stories, not RGL                                      |
| `DashboardWidgetsOverview.stories.tsx` heights     | Overview showcase scale, separate from live mins                      |
| Changing `MIN_WIDGET_TILE_HEIGHT_ROWS` globally    | Affects **unknown** widget types only; prefer per-type catalog `minH` |

### Change checklist

1. Edit `defaultLayout.minH` / `minW` in `widget_types/catalog.ts` for the `widget_type`.
2. Extend `frontend/src/scenes/dashboard/tileLayouts.test.ts` — parameterized case with `expectedMinH` / `expectedMinW` for that `widget_type` (see `error_tracking_list` / `session_replay_list` examples).
3. Run `hogli test frontend/src/scenes/dashboard/tileLayouts.test.ts`.
4. Manually resize the tile in dashboard **edit mode** to confirm the floor.
5. Optional: add a `MinimumSize` story — frame height `minH * 80` px, limit demo data so content fits.

### Storybook vs dashboard

- **Dashboard:** mins from catalog → `tileLayouts.ts` → RGL.
- **Storybook tile stories:** optional fixed frame (`widgetCardStoryFixtures` or per-story wrapper). A `MinimumSize` story documents the floor; it does not change production behavior.

## Add widget modal

- Title: **Add widget**; description: **Bring context from your different PostHog products into one dashboard.**
- `AddWidgetModal` supports **multi-select** — pick one or more catalog variants, then "Add N widgets"
- `dashboardLogic.addWidgetTiles` → `POST .../widgets/batch/` (1–10 tiles)
- Backend placement: `widget_layouts.stack_widget_layout_at_bottom` — new tiles append on the **bottom row** of the dashboard (batch adds pack horizontally, then wrap)
- REST/MCP add: `dashboard-widgets-batch-add` — same batch endpoint; one tile = single-element `widgets`. See [mcp.md](mcp.md)

## NEW badge (Add menu)

Surface the Widget entry as new in the Add menu:

- Populated dashboard: `DashboardHeaderActions` — `LemonMenu` item `tag: 'new'`
- Empty dashboard: `EmptyDashboardComponent` — inline `<LemonTag type="success" size="small">NEW</LemonTag>` on the Widget menu item

Do not add NEW badges on individual catalog variants inside `AddWidgetModal`.

## Config updates

- `updateWidgetTile` in `dashboardLogic` → `updateDashboardWidgetTile` (one PATCH) → `refreshDashboardWidgets` when config changed
- Widget settings modal: Zod validate → `LemonField` errors; disable save while `saving` / invalid
- Title, description, `filterTestAccounts`, and type-specific fields all live in the settings modal (`EditWidgetModal*` sections) — not inline on the card

## Remove and undo

- Remove: no confirm dialog — undo toast (`removeTileSuccess` in `dashboardLogic.tsx`)
- Copy: "widget removed" + Undo

## ⋯ menu parity (`DashboardWidgetItem`)

- View (if `titleHref`)
- Edit (opens widget settings modal)
- Duplicate
- Show/hide description (toggle visibility; edit text in settings modal)
- Dashboard section: copy/move to another dashboard, remove
- Refresh data — direct click with optional "Last computed" subtitle (`dashboard_tile` header layout; omitted for unknown widget types)

## Header layout choice

Prefer `headerLayout: 'dashboard_tile'` for new widgets — matches insight tile chrome; Refresh data is a direct ⋯ menu item (optional "Last computed" subtitle), same as insight tiles.

See [composition.md](composition.md) for header layout details.

## Date range in config

Store time period in `config.dateRange` (insight-shaped `{ date_from, date_to?, explicitDate? }`).

Supported relative `date_from` values (shortest first): `-1h`, `-3h`, `-24h`, `-7d`, `-14d`, `-30d`, `-90d` — defined in FE `configSchemas.ts` (`WIDGET_DATE_FROM_VALUES` / `WIDGET_DATE_RANGE_SELECT_OPTIONS`) and BE `backend/constants.py` (`WIDGET_DATE_FROM_VALUES`). Keep both in sync when adding or removing values; update BE `config_schema_hints` and `widget_openapi_serializers.py` too.

Format for display via `WidgetCardHeader` — reads `config.dateRange` + catalog `headerMeta` and formats with `dateFilterToText`.

## Description display

When `show_description` is enabled, the card header renders markdown under the title (`WidgetCardHeader` / `CardMeta`) with `max-h-24 overflow-y-auto`.

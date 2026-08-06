# List widget patterns

**When to load:** Shipping or updating a **list/table** widget (`error_tracking_list`, `session_replay_list`, or the next list type).

Edit modal and WidgetCard chrome: [composition.md](composition.md). Date range display: [layout-and-ux.md](layout-and-ux.md).

Shipped reference: `error_tracking_list`, `session_replay_list`.

## Tile filter bar (`widgetFilters`)

**`widgetFilters`** on config (persisted property filter selections). Edit modal = test accounts + limit + sort. Tile bar = date + type pickers + property filters.

| Layer               | Path                                                                                                                 |
| ------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Zod (generated)     | `widget-configs.zod.ts` (config + form schemas, types — import directly)                                             |
| Zod (form/modal)    | `*WidgetConfigValidation.ts` (`.pick()` on config schema), `widgetConfigShared.ts` (UI labels only)                  |
| FE helpers          | `widgetFilters.ts`                                                                                                   |
| BE validate + HogQL | `backend/widgets/widget_filters.py` — generic `validate_widget_filters` + `build_*_from_widget_filters`              |
| Tile bar            | `*WidgetTileFilters.tsx`, `widgetTileFiltersHooks.ts` (`useWidgetTileConfigPersist`), `WidgetPropertyFiltersSection` |
| Tile bar mount      | `DashboardWidgetItem` — registry `TileFilters` only when `hasProductAccess && showTileFilters`                       |

`canEditDashboard` gates edit vs read-only bar (`DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON` in `constants.ts`). RBAC denial hides the bar entirely (body shows locked state). Not coupled to the dashboard quick-filter bar.

Checklist: `*WidgetTileFilters.tsx` + registry `TileFilters`; persist `widgetFilters` on config — [checklist §5](checklist-new-widget-type.md#5-frontend-widget-component).

## Pagination footer

| Layer   | Responsibility                                                                                                                                                                                                                                                                  |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run_*` | `results`, `hasMore`, `limit`, `offset`. `!hasMore` → `totalCount` = shown. `hasMore` + `include_total_count=True` → capped count query (`MAX_WIDGET_RESULT_LIMIT`). **Dashboard** `run_widgets` always passes `include_total_count=False` — skip count when page has more rows |
| FE      | `WidgetCardContent` **`footer`**: `formatWidgetListCountFooter(shown, totalCount, totalCountCapped, noun, hasMore)` — nouns in `constants.ts` (`WIDGET_LIST_COUNT_ISSUES` / `RECORDINGS`). Omit total + `hasMore` → `N+` copy                                                   |
| Stories | When mocking `hasMore: true`, either totals or rely on `hasMore` for `N+` footer                                                                                                                                                                                                |

Count failures never fail the tile (log + omit totals).

## Header title navigation

- Catalog **`titleHref`** — product scene route (`urls.errorTracking()`, `urls.replay()`, …).
- **`WidgetCardHeader`** wraps the title in `<Link>` when `titleHref` is set and **`isDashboardEditMode` is false** — do not gate on `showEditingControls` (editable dashboards keep editing chrome in view mode).
- **`DashboardItems`** sets `isDashboardEditMode={dashboardMode === DashboardMode.Edit}` on `DashboardWidgetItem`.
- Dashboard **layout edit mode** keeps the title plain text so header drag does not compete with navigation; ⋯ **View** still uses `titleHref`.
- Public placement: `titleHref` suppressed in `DashboardWidgetItem` (existing sharing rules).

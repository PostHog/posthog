# Dashboards v2

A layout primitive for dashboards that any PostHog team can build on.
It covers the grid, tiles, sections, tabs, and the drag and resize behavior.

Update this file in the same change whenever a rule below changes.

## The model

A dashboard has tabs. A tab has one grid. A grid holds tiles, and nothing else.

| Term    | Meaning                                                                      |
| ------- | ---------------------------------------------------------------------------- |
| Tile    | One cell-aligned box in a grid, with a place: `x`, `y`, `w`, `h`.            |
| Widget  | What a tile shows: a number, a chart, text, or a section.                    |
| Section | A widget that is itself a grid. A section can sit inside another section.    |
| Tab     | A named grid. Tabs belong to the dashboard only. A section cannot hold tabs. |

The whole dashboard is one JSON tree (`Dashboard` in `frontend/dashboard/dashboardTypes.ts`).
It has a `title` and an optional `description`, shown under the title.

## Tabs

A tab holds a grid of tiles, or is a link elsewhere: `{ id, title, tiles }` or `{ id, title, href }`.
A link tab opens a PostHog path or a full URL in a new browser tab. It holds no tiles, so a tile cannot move to it.
A dashboard keeps at least one tab with tiles, and a link tab never becomes the tab that shows.

## The grid

- A tab's grid has 24 columns. A row is 10px tall and the gap between tiles is 12px, so heights move in 22px steps.
- A tile's place is in whole columns and rows.
- A tile added to a grid scrolls into view.
- Tiles never overlap, and no tile has an empty row above it that it could move into.

## Sections

A section is drawn as a card inside its own space, like a tile, so sections side by side keep the grid gap between them.
Its grid has one column for each column the section covers, and sits 12px in from the card's sides (`GRID.sectionInsetPx`).
So tiles inside a section are slightly narrower than the same number of columns outside it, and do not line up with them.
A tile keeps its column count when it moves in or out of a section, unless the grid it lands in is narrower than the tile or the row it joins is full.

A section is resized like a tile, from any edge or corner. Its height is at least the rows for its card header and the padding above and below its tiles (`GRID.sectionChromeRows`), plus the rows its tiles need. A section resized taller keeps that height (`minRows`) and still grows when its tiles need more. Resized back down to what its tiles need, it follows them again.
A closed section is three rows, enough for its card's header (`GRID.collapsedSectionRows`). An empty open section keeps four rows for its tiles, so it can take a drop.
Anyone can open or close a section, for their own view only. It is not saved and is not an undo step.
A section cannot be resized narrower than its tiles need.
A section moved into a narrower grid gets narrower, and its tiles are placed again to fit.
A section's tiles can be laid out in 1 to 4 equal columns with Auto layout in its menu (`autoLayout`). Its tiles fill the columns row by row in reading order and keep their heights.

## Where a tile goes

One function decides every place: `placeTiles` in `frontend/grid/placeTiles.ts`.
A drag inside a grid, a drop from another grid, and a saved dashboard all go through it.

1. With no drag or resize running, tiles only move up to close gaps.
2. During a drag or resize, every other tile starts from where it was when the gesture began.
   The result depends on where the pointer is now, not on the path it took.
3. A tile dropped on the upper half of a row joins that row.
   The row's tiles keep their order and slide apart to make room.
4. If the row is full, its tiles get narrower to fit, down to each widget's minimum width.
   The row does not wrap.
5. If the row cannot get narrow enough, the tile takes that place and whatever it lands on moves down.
6. A tile dropped on the lower half of a row goes under that row.
7. A resize never changes another tile's width. Tiles in the way move down.

## Drag and resize

`react-grid-layout` moves and sizes the tiles inside one grid (`frontend/grid/TileGrid.tsx`). The grid knows nothing of the dashboard: `frontend/tiles/DashboardTileGrid.tsx` hands it the tiles to draw and turns its moves into edits.
It does not decide places: its compactor is `placeTiles`.

- A tile is dragged by its title bar. A tile without a title is dragged by its body. A section is dragged by its header.
- The tile follows the pointer. A dashed outline shows where it will land, and it lands exactly there.
- While a tile is over another grid, that grid shows the outline and makes room.
  The tile's own grid closes up.
- The grid a tile is over is decided from where every grid was when the drag began (`frontend/grid/dropTargets.ts`).
  A preview moves and resizes grids, so reading them during the drag makes the outline jump between two grids.
- A tile leaves a section when the pointer leaves the area the section covered when the drag began.
- A tile dropped on another tab's name moves to the bottom of that tab.
- A section grows while a tile is dragged or resized inside it, and the tiles below it move down.
- A tile or an open section resizes from any edge or corner. A closed section resizes in width only.

## Editing

- Every change goes through one pure function, `applyEdit` in `frontend/dashboard/dashboardEdits.ts`, and comes out settled: no overlaps, no gaps, and correct section heights.
- Tabs can be added, renamed, and removed. The last tab cannot be removed.
- Undo and redo cover every edit, and a press that moves nothing adds no undo step.
- Only people who can edit dashboards can change the layout. Everyone else sees it read-only.

## Embedding a dashboard

The frontend is grouped by concept: `dashboard/`, `grid/`, `tiles/`, `widgets/`, `presentation/` and `access/`. Only the `/dashboard-v2` host, `DashboardV2Scene.tsx` and `dashboardV2Logic.ts`, sits at the root.

The components hold no business logic and never import a kea logic, so any page can render a dashboard.

- `DashboardV2View` in `frontend/dashboard/DashboardV2View.tsx` renders the tabs and the grid from a `DashboardV2Controller` (`frontend/dashboard/dashboardV2Context.ts`).
- The host owns the dashboard, undo history, access rules, saving and the URL. `recordEdit`, `undoEdit` and `redoEdit` in `frontend/dashboard/dashboardHistory.ts` give every host the same undo behavior, and `useDashboardHistory` wraps them for a host that keeps its dashboard in React state. It passes values in and gets edits back through `onEdit`.
- The view owns only what the screen and a drag decide: the stacked layout on narrow screens, the drop target, and the undo shortcut.
- The view passes the controller down through context. The drop target has a context of its own, so a drag re-renders only what reads it.
- `dashboardV2Logic` is the host for the `/dashboard-v2` scene. Another product supplies its own host, and its own header through the `header` slot.
- When a dashboard can't load, the host can render `DashboardV2Unavailable` (`frontend/dashboard/DashboardV2Unavailable.tsx`) in place of the view. Each problem has a default hedgehog, title and description, and the host can replace any of them or add `actions`, such as a link back to its own list.

## Narrow screens

Below 768px of canvas width (`GRID.stackBelowPx`), every tile is full width and tiles cannot be dragged or resized.

- Tiles stack in reading order: top to bottom, then left to right. Sections stack their own tiles the same way.
- Text and number tiles keep their height. Line and bar charts stay between 10 and 16 rows, so one chart never fills the screen.
- The stacked layout is worked out from the saved one each time and is never saved.
- Only arranging tiles (`placeTiles`) is refused. Other edits, such as moving a tile to another tab, still work.
- A disabled menu entry shows its reason under its label, since a touch screen shows no tooltip.

## Widgets

The dashboard does not know any widget type. The host passes the types it supports as `widgets` on the controller.

A type has two parts, so code outside the browser can use the first without React:

- A `WidgetSpec` (`frontend/widgets/widgetSpec.ts`) is plain data: its add menu items, its default and minimum size, a zod `configSchema` for the widget's `config`, and whether its data refreshes.
- A `WidgetDefinition` (`frontend/widgets/widgetDefinition.ts`) is the spec plus the `Component` that renders it. The controller takes these.

A widget's own fields sit in `config`. The fields every tile has (`type`, `title`, `description`, `refreshedAt`, `parts`) sit beside it.
A tile's `description` shows in a tooltip on an info icon beside its title.
A tile is dragged by its header, or by its body when it has no header. A widget marks text people should be able to select with the `TileGrid__text` class, and pressing on it selects instead of dragging.

How the dashboard uses them:

- The add menu lists every add menu item of the host's widgets, then Section. A section is part of the grid, so it is built in and has no spec.
- A saved widget whose type is not in the list keeps a place in the grid and shows that the dashboard can't render it.
- The layout functions in `frontend/grid/gridTiles.ts` take a `sizeOf` function instead of importing widgets. Build it from specs with `sizeOfWidgets`. The view does this itself, and a host that calls `applyEdit` does the same.
- `DEFAULT_WIDGETS` in `frontend/widgets/defaultWidgets.ts` is the set that ships with dashboards v2. A host can pass it, a subset, or its own list.

A widget type can also:

- add controls to its tile's header with `HeaderActions`, such as an interval picker or an "Open as insight" button;
- replace what its footer shows with `Footer`;
- set what its tile shows while its component suspends with `Loading`. Without it, the tile shows `WidgetLoading`, a skeleton a widget can also render itself while it loads;
- change its tile's right-click menu: `menuActions` adds entries, and `tileActions(actions, { widget })` receives the whole list to remove, disable, reorder or add entries by `key`.

A host can also pass `tileActions(actions, { id, widget })` on the controller. It runs last, for content tiles and sections, so a page can hide `remove` everywhere or `chart-type` on one dashboard. The order is built-in actions, widget `menuActions`, widget `tileActions`, host `tileActions`. The built-in keys are listed on `MenuAction.key`.

The dashboard has its own menu, beside undo and redo. Its built-in action, `download-image`, downloads the active tab as a PNG or WebP image, with every tile drawn first. A host passes `dashboardActions(actions)` on the controller to hide, disable or add entries the same way.

To hide a tab from someone, such as a tab behind a feature flag, the host leaves it out of the dashboard it passes in. Whatever the host passes reaches the browser, so tabs a person may not see are removed where the dashboard is loaded, not in the view.

To add a widget type, write its spec and component in `frontend/widgets/<type>/`, then pass `defineWidget({ ...spec, Component })` in the host's list.

### One widget on its own

`WidgetCard` in `frontend/tiles/WidgetCard.tsx` renders one widget in its card, with no dashboard around it: `<WidgetCard widget={widget} widgets={DEFAULT_WIDGETS} />`.
Inside a dashboard, `ContentTile` renders the same card with the tile's actions.

### Hiding tiles for one view

`withoutTiles(dashboard, ids, sizeOf)` removes tiles from what one person sees, such as a tile with nothing to show yet, and closes the gaps they leave.
It is never saved, so the tiles return to their places when they are shown again.
Combine it with `withFolds` in the dashboard the host passes to the view, and pass the same function as the view to `applyEdit`.

### Charts

A chart is one widget type, `chart`, whose config is a query and a kind of chart: `{ query, viz: { type, options } }`.
The query is `{ language, query }` in one of three languages: `hogql` with a HogQL `SELECT`, `metrics` with a `MetricsQuery` node, or `traces` with a `TraceSpansQuery` or `TraceSpansAggregationQuery` node.
The data and the way it is drawn are separate, so changing a chart from a line to a bar never runs its query again.

- A kind of chart is a `VizSpec` (`frontend/widgets/chart/vizType.ts`): a label, a size, and a zod schema for its options. A `VizDefinition` adds the component that draws a query result.
- `createChartWidget({ extraVizTypes, runQuery, states, menuActions })` builds the chart widget type. It draws every built-in kind of chart, so a dashboard saved by another host still renders. A host adds its own kinds with `extraVizTypes` and supplies `runQuery`, so the dashboard never fetches data itself. `runQuery` gets `{ query, time }` and returns `{ frames, fetchedAt?, stale? }`. A query's `language` is `hogql`, `metrics`, `traces`, or `insight` for any node `/query` runs. In the request, `time` is the chart's own `config.time`, or else the range from `TimeRangeContext`, which `DashboardV2View` fills from the dashboard's `time` (default `now-7d` to `now`).
- A query result is a list of `DataFrame`s. A kind of chart only draws rows. Loading, empty and error states come from the kind of chart if it sets them, then from the `states` the host passes to `createChartWidget`, then from built-in ones. The built-in kinds set a skeleton shaped like their chart, and a host's `states` replace the built-in kinds' states but not those of its own kinds. A kind of chart can also decide what counts as empty with `isEmpty`.
- When a chart's time range or query changes, the tile keeps its last result on screen, faded, until the new one arrives.
- The add menu has one "Chart" item, which starts as a line chart. The tile's "Chart type" menu switches its kind, and its "Chart options" menu sets the options that kind declares. A chart takes its size from its kind of chart.

To add a kind of chart, write its spec and component in `frontend/widgets/chart/viz/<type>/`. Pass it as `extraVizTypes`, or add it to `DEFAULT_VIZ_TYPES` in `frontend/widgets/chart/createChartWidget.tsx` to ship it with dashboards v2.

## Dashboards as code

A dashboard is one JSON document, so it can live in a repo or be written by a tool.
The zod schemas in `frontend/dashboard/dashboardSchema.ts` are the only definition of the document: its types are inferred from them.
`validateDashboard(document, specs)` in `frontend/dashboard/validateDashboard.ts` checks a document against them before it loads, and returns each problem with its path.

- It reports a document that is not a v2 dashboard, an unknown widget type, a missing or misspelled widget field, a tile smaller than its widget's minimum, a tile past the edge of its grid, and an id used twice.
- Overlaps and gaps are not problems, because loading a dashboard settles them.
- It needs only specs, so a CI check or an MCP tool can run it without rendering anything.

A widget can show on more than one tile, such as the same chart on two tabs.
The document stores it once, in `widgets`, and each tile points at it with `{ "ref": "<key>" }`, plus its own `parts` and `appearance`.
Its type, title, description and config are shared, so changing a chart's query or kind on one tile changes it on every tile.
Size, position, parts and appearance belong to each tile.

- `loadDashboard(document)` in `frontend/dashboard/sharedWidgets.ts` puts each shared widget back on its tiles, with `ref` set, so the rest of the code sees whole widgets. `saveDashboard(dashboard)` stores them once again and drops any no tile shows.
- "Also show on tab" in a tile's menu (`addToGrid`) places a second tile for the same widget on another tab. Removing either tile leaves the other.
- `validateDashboard` reports a tile pointing at a widget the document does not have.

## Checking a change

Layout bugs show up under a real pointer, not in a unit test.

1. `frontend/grid/placeTiles.test.ts` covers the placement rules as a table. Add a row for a new rule.
2. The stories in `frontend/DashboardV2Scene.stories.tsx` drag real tiles in a browser and assert that each one lands on its outline with nothing overlapping. Add a story for a new gesture.
3. Try the gesture by hand with a real pointer.

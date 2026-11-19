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

The whole dashboard is one JSON tree (`Dashboard` in `frontend/layout/dashboardTypes.ts`).

## The grid

- A tab's grid has 24 columns. A row is 32px tall. The gap between tiles is 12px.
- A tile's place is in whole columns and rows.
- Tiles never overlap, and no tile has an empty row above it that it could move into.

## Sections line up with the grid around them

A section's grid has one column for each column the section covers, and no padding.
Its header is one row tall, and the gap under the header is the grid gap.
So every cell inside a section sits exactly on a cell of the grid outside it, at any depth.
A tile keeps its size when it moves in or out of a section, unless the grid it lands in is narrower than the tile or the row it joins is full.

A section's height is never chosen. It is one row for the header plus the rows its tiles need.
A closed section is one row. An empty open section keeps two rows, so it can take a drop.
Anyone can open or close a section, for their own view only. It is not saved and is not an undo step; the saved state is the default everyone sees first.
A section cannot be resized narrower than its tiles need.
A section moved into a narrower grid gets narrower, and its tiles are placed again to fit.

## Where a tile goes

One function decides every place: `placeTiles` in `frontend/layout/placeTiles.ts`.
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

`react-grid-layout` moves and sizes the tiles inside one grid (`frontend/components/TileGrid.tsx`).
It does not decide places: its compactor is `placeTiles`.

- A tile is dragged by its title bar. A tile without a title is dragged by its body. A section is dragged by its header.
- The tile follows the pointer. A dashed outline shows where it will land, and it lands exactly there.
- While a tile is over another grid, that grid shows the outline and makes room.
  The tile's own grid closes up.
- The grid a tile is over is decided from where every grid was when the drag began (`frontend/layout/dropTargets.ts`).
  A preview moves and resizes grids, so reading them during the drag makes the outline jump between two grids.
- A tile leaves a section when the pointer leaves the area the section covered when the drag began.
- A tile dropped on another tab's name moves to the bottom of that tab.
- A section grows while a tile is dragged or resized inside it, and the tiles below it move down.
- Resize handles are on the right edge, the bottom edge, and the corner. A section resizes in width only.

## Editing

- Every change goes through one pure function, `applyEdit` in `frontend/layout/dashboardEdits.ts`, and comes out settled: no overlaps, no gaps, and correct section heights.
- Tabs can be added, renamed, and removed. The last tab cannot be removed.
- Undo and redo cover every edit, and a press that moves nothing adds no undo step.
- Only people who can edit dashboards can change the layout. Everyone else sees it read-only.

## Narrow screens

Below 768px of canvas width (`GRID.stackBelowPx`), the dashboard is read-only and every tile is full width.

- Tiles stack in reading order: top to bottom, then left to right. Sections stack their own tiles the same way.
- Text and number tiles keep their height. Line and bar charts stay between 5 and 8 rows, so one chart never fills the screen.
- The stacked layout is worked out from the saved one each time and is never saved.
- Every edit is refused, and disabled controls say to open the dashboard on a wider screen.

## Adding a widget type

1. Add the type to `ContentWidget` in `frontend/layout/dashboardTypes.ts`.
2. Add its default and minimum size to `frontend/layout/widgetSizes.ts`.
3. Render it in `frontend/widgets/WidgetView.tsx`.
4. Add it to the add menu in `frontend/widgets/newTiles.ts`.

The grid never looks inside a widget, so no layout code changes.

## Checking a change

Layout bugs show up under a real pointer, not in a unit test.

1. `frontend/layout/placeTiles.test.ts` covers the placement rules as a table. Add a row for a new rule.
2. The stories in `frontend/DashboardV2Scene.stories.tsx` drag real tiles in a browser and assert that each one lands on its outline with nothing overlapping. Add a story for a new gesture.
3. Try the gesture by hand with a real pointer.

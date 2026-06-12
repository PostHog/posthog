# BoldNumber

Renders a trend result as a single large number, with an optional comparison against the previous period and a hover tooltip for inspecting actors.

## Exports

- `BoldNumber` (`BoldNumber.tsx`, re-exported from `index.ts`) — takes `ChartParams` (`showPersonsModal`, `context`) and reads the result to display from `insightVizDataLogic` (`insightData`, `trendsFilter`, `compareFilter`).
  Shows an up/down/flat trend indicator when compare is enabled, and opens the persons modal on click.
- `HogQLBoldNumber` — variant for SQL insights; reads the first cell of the response from `dataVisualizationLogic` and shows an empty state when the value is null.
- `computeComparisonDisplay(currentValue, previousValue)` — pure helper returning `{ percentageDiff, hasComparableDiff, displayText }` ("Up 12% from", "Down 5% from", "No change from").
- `Textfit` (`Textfit.tsx`) — auto-scales its text content between `min` and `max` font sizes to fit the container; used for the number itself.

## Chart.js plugins

None — this is plain DOM rendering, no canvas.
The tooltip is rendered through `useInsightTooltip` from `../InsightTooltip`.

## Consumers

- `common/query-frontend/src/nodes/TrendsQuery/Trends.tsx` — trends insights with the bold number display type
- `common/query-frontend/src/nodes/DataVisualization/DataVisualization.tsx` — SQL insights (`HogQLBoldNumber`)
- `frontend/src/scenes/data-warehouse/editor/OutputPane.tsx` — SQL editor output pane

## Known debt

`BoldNumber` reads from `insightLogic`, `insightVizDataLogic`, `teamLogic`, and `groupsModel`, and `HogQLBoldNumber` from `dataVisualizationLogic`.
Like `LineGraph`, this coupling is slated to be unwound toward a props-driven API.

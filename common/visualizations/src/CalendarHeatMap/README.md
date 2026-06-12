# CalendarHeatMap

Calendar heatmap display for trends: a day-of-week × hour-of-day matrix with row, column, and overall aggregations, shown in the project's timezone.

## Exports

- `TrendsCalendarHeatMap` (`TrendsCalendarHeatMap.tsx`, re-exported from `index.ts`) — takes `ChartParams` (currently unused).
  Data (`processedData`, `rowLabels`, `columnLabels`) comes from `calendarHeatMapLogic`; rendering is delegated to the generic `CalendarHeatMap` component from `scenes/web-analytics/CalendarHeatMap`.
  A footer shows the active timezone with a link to the project's date and time settings.
- `calendarHeatMapLogic` (`calendarHeatMapLogic.tsx`) — kea logic keyed by `InsightLogicProps` that buckets `TrendResult` values into the matrix (`CalendarHeatMapProcessedData`) with per-row/column/overall aggregations.
- `utils.ts` — axis configs (`DaysAbbreviated`, `HoursAbbreviated`), `AggregationLabel`, tooltip text builders (`getDataTooltip`, `getRowAggregationTooltip`, `getColumnAggregationTooltip`, `getOverallAggregationTooltip`), and `thresholdFontSize`.

## Chart.js plugins

None — the heatmap is DOM/SVG rendering via the shared web analytics `CalendarHeatMap` component.

## Consumers

- `common/query-frontend/src/nodes/TrendsQuery/Trends.tsx` — trends insights with the calendar heatmap display type

## Known debt

`TrendsCalendarHeatMap` reads from `insightLogic`, `teamLogic`, and `insightVizDataLogic` (via its logic), and still imports the presentational component from `scenes/web-analytics`.
New chart components should be props-driven and self-contained instead (see the package README).

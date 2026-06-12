# BoxPlot

Box-and-whisker chart for trends results, plus a matching legend and results table.

## Exports

- `BoxPlotChart` (`BoxPlotChart.tsx`, re-exported from `index.ts`) — takes `ChartParams` (`showPersonsModal`).
  Series data comes from `boxPlotChartLogic`, which derives `BoxPlotSeriesData[]` (min/p25/median/mean/p75/max per interval) from the insight response.
  Hovering shows an `InsightTooltip` listing the six stats per series, and clicking opens the persons modal via an `InsightActorsQuery`.
- `boxPlotChartLogic` (`boxPlotChartLogic.tsx`) — kea logic exposing `BoxPlotChartDatum` / `BoxPlotSeriesData` and the chart-ready datasets.
- `BoxPlotLegend` (`BoxPlotLegend.tsx`) — legend explaining the box anatomy; props: `horizontal`, `inCardView`.
- `BoxPlotResultsTable` (`BoxPlotResultsTable.tsx`) — tabular view of the same stats below the chart.

## Chart.js plugins

Relies on `BoxPlotController` and `BoxAndWiskers` from `@sgratzl/chartjs-chart-boxplot`, which are registered globally in `@posthog/visualizations/Chart` — there are no plugin imports in this folder itself.

## Consumers

- `common/query-frontend/src/nodes/TrendsQuery/Trends.tsx` — trends insights with the box plot display type
- `common/query-frontend/src/nodes/InsightViz/InsightVizDisplay.tsx` — legend/table placement around the insight
- `frontend/src/exporter/ExportedInsight/ExportedInsight.tsx` — exported/embedded insight rendering

## Known debt

`BoxPlotChart` and `boxPlotChartLogic` read from `insightLogic`, `teamLogic`, and query-frontend logics, so the component only works inside an insight context.
New chart components should be props-driven instead (see the package README).

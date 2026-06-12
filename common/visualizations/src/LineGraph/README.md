# LineGraph

The main Chart.js-based insight renderer.
Renders line, bar, horizontal bar, and area graphs, and delegates to `PieChart` when `type === GraphType.Pie`.

## Exports

- `LineGraph` (`LineGraph.tsx`) — error-boundary wrapper that picks `PieChart` or the internal `LineGraph_` based on `type`.
  Key props (`LineGraphProps`): `datasets: GraphDataset[]`, `labels: string[]`, `type: GraphType`, `onClick`, `tooltip: TooltipConfig`, `trendsFilter`, `formula`, `isArea`, `isStacked`, `incompletenessOffsetFromEnd` (dotted in-progress segment), `showPercentStackView`, `showMultipleYAxes`, `yAxisScaleType`, `goalLines`, `showTrendLines`, `anomalyPoints`, `hideAnnotations`, `legend`, `inCardView`, `onDateRangeZoom`, and a required `data-attr`.
  Caps rendering at 150 datasets (`MAX_CHART_DATASETS`) to keep the main thread responsive.
- `PieChart` (`PieChart.tsx`) — pie rendering with datalabels; extends `LineGraphProps` with `breakdownFilter`, `showLabelOnSeries`, `disableHoverOffset`, and `valueFormatter`.
- `onChartClick`, `onTooltipClick`, `onChartHover` — shared Chart.js event handlers that translate clicks into `GraphPointPayload` (used by the persons modal flow).
- `createTooltipData` (`tooltip-data.ts`) — maps Chart.js `TooltipItem[]` to the `SeriesDatum[]` shape `InsightTooltip` consumes, sorted by count.
- `ConfidenceLevelInput`, `MovingAverageIntervalsInput` — trends display option inputs that write `confidenceLevel` / `movingAverageIntervals` into the query's `trendsFilter` (debounced).

## Chart.js plugins

Registered/used at component level: `chartjs-adapter-dayjs-3` (time axis), `chartjs-plugin-annotation` (goal lines), `chartjs-plugin-datalabels` (values on series), `chartjs-plugin-stacked100` (percent stack view), `chartjs-plugin-trendline`.
Crosshair, zoom, and the box plot controller come pre-registered from `@posthog/visualizations/Chart`.
X-axis tick callbacks come from `@posthog/quill-charts`.

## Consumers

Trends, stickiness, and lifecycle queries (`common/query-frontend/src/nodes/TrendsQuery/viz/` — `ActionsLineGraph`, `ActionsHorizontalBar`, `ActionsPie`), funnel trends (`FunnelsQuery/FunnelLineGraph`), retention (`RetentionQuery/RetentionGraph`), SQL insights (`DataVisualization/Components/Charts/PieChart`), surveys question visualizations (`frontend/src/scenes/surveys/`), and revenue analytics nodes (`products/revenue_analytics/`).

## Known debt

`LineGraph`, `PieChart`, and the two inputs read from `insightLogic`, `insightVizDataLogic`, `trendsDataLogic`, `teamLogic`, `groupsModel`, and `themeLogic`.
This coupling to the insight pipeline is being unwound — new charts should be props-driven instead (see the package README).

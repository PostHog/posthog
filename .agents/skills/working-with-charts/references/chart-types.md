# Choosing a chart type

Pick by the shape of the data and the question the user asks of it.
The library `AGENTS.md` lists every component and every config key; this file adds the app's own precedents so you copy a working adapter instead of starting from the props table.

## Decision table

| The data is...                                                             | Reach for                                                                      | App precedent                                                                                                                                                                        |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Values over time, one point per bucket, the path between points matters    | `TimeSeriesLineChart` (`fill: {}` per series for area)                         | `products/product_analytics/frontend/insights/trends/TrendsLineChart/`, `products/product_analytics/frontend/insights/retention/RetentionLineChart/`                                 |
| Values over time where magnitude per bucket matters more than the path     | `TimeSeriesBarChart` (`barLayout: stacked \| grouped \| percent`)              | `products/product_analytics/frontend/insights/trends/TrendsBarChart/` (time-series branch), `products/product_analytics/frontend/insights/trends/TrendsLifecycleChart/`              |
| Bars and lines on one time axis (a count with a rate, revenue with margin) | `TimeSeriesComboChart` (`type` per series)                                     | `frontend/src/queries/nodes/DataVisualization/Components/Charts/SqlComboGraph.tsx`                                                                                                   |
| Categories, not dates, on the x-axis                                       | `BarChart` (vertical) or `LineChart`                                           | `frontend/src/scenes/surveys/components/question-visualizations/RatingBarChart.tsx`                                                                                                  |
| One value per category, ranked, long labels                                | `BarChart` with `axisOrientation: 'horizontal'`                                | `TrendsBarChart` aggregated branch (bar value display), `MultipleChoiceBarChart.tsx`                                                                                                 |
| Share of a whole, a handful of categories                                  | `PieChart` (`innerRadiusRatio` for a donut)                                    | `products/product_analytics/frontend/insights/trends/TrendsPieChart/`                                                                                                                |
| A thin proportion strip inside a table row                                 | `BarChart`, horizontal, `barLayout: 'percent'`, chrome hidden                  | `products/error_tracking/frontend/components/Breakdowns/BreakdownsStackedBar.tsx`                                                                                                    |
| Funnel steps, one bar per step or per variant                              | `FunnelChart`                                                                  | `products/product_analytics/frontend/insights/funnels/FunnelStepsBarChart/`, `frontend/src/scenes/experiments/charts/funnel/ExperimentFunnelChart.tsx`                               |
| Distribution per category (`min`, `p25`, `median`, `mean`, `p75`, `max`)   | `BoxPlot`                                                                      | `frontend/src/scenes/insights/views/BoxPlot/BoxPlotChart.tsx`, `products/engineering_analytics/frontend/components/LeadTimeBoxPlot.tsx`                                              |
| Two continuous measures per point, correlation or clusters                 | `ScatterChart` (`onAreaSelect` for zoom)                                       | `products/ai_observability/frontend/clusters/ClusterScatterPlot.tsx`, `frontend/src/queries/nodes/DataVisualization/Components/Charts/SqlScatterGraph.tsx`                           |
| Density on a 2D grid (latency over time)                                   | `Heatmap` (`onBrush`)                                                          | `products/tracing/frontend/TracingLatencyHeatmap.tsx`                                                                                                                                |
| Change between exactly two points across many series                       | `SlopeChart`                                                                   | `products/product_analytics/frontend/insights/trends/TrendsSlopeChart/`. See also `/visualizing-change-over-time`.                                                                   |
| A trend at a glance, no axes, in a card or a row                           | `Sparkline` (`type: 'bar'` for buckets)                                        | `frontend/src/lib/components/Sparkline.tsx` (the app wrapper), `products/logs/frontend/components/LogsViewer/LogsViewerSparkline/index.tsx` (a `TimeSeriesBarChart` with chrome off) |
| A headline number with a change pill and a sparkline                       | `MetricCard`, or `Metric` from `@posthog/quill-components` for a custom layout | `frontend/src/queries/nodes/OverviewGrid/OverviewMetricCardGrid.tsx`, `frontend/src/scenes/insights/views/Metric/Metric.tsx`                                                         |

## Rules of thumb

- **Time on the x-axis means the `TimeSeries*` wrapper.** It formats ticks from `xAxis.timezone` and `interval`, formats the tooltip header to match, takes `goalLines`, `legend`, `valueLabels`, `trendLines`, `movingAverage`, `confidenceIntervals` as config, and handles multi-axis `yAxis` arrays. Only reach for the base `LineChart` / `BarChart` when the labels are categories.
- **Line when the path matters, bar when the bucket matters.** A daily count reads as a line; a per-release or per-week comparison reads as bars. Area is a line with `fill`, for emphasis on volume or for stacking (`percentStackView`).
- **Stacked bars for parts of a whole per bucket, grouped bars for comparing series side by side.** Compare-to-previous on trends uses grouped bars so each period gets its own bar. Percent stacks answer "what share" rather than "how many".
- **Pie only for a few slices that sum to a whole.** Past about eight categories, a horizontal bar reads better and the legend stops scrolling.
- **Funnels are `FunnelChart`, not a hand-built stacked bar.** It owns the hatched drop-off track, the percent axis, `onStepClick` with `converted` versus drop-off, and `stepFooter` for per-step legends.
- **A goal that should stretch the axis is a `goalLines` config entry; a marker that should not is a `ReferenceLine` child.** Experiments draw their zero line as a goal line so zero stays on the plot.
- **Multiple magnitudes on one chart get their own axes.** `showMultipleYAxes` on trends assigns `yAxisId` per magnitude cluster through `computeMagnitudeAxisIds`. A `0..1` probability or a `0..100` percentage on a secondary axis should pin `min` and `max` so reference lines stay on the plot.
- **A chart the user cannot hover is a sparkline.** Hide axes, grid, crosshair, and tooltip, and surface the hovered value in a sibling element through `useChartHover()` if you need it.

## Insight display types

`frontend/src/scenes/trends/Trends.tsx` maps `ChartDisplayType` to a component.
Line, area, and cumulative all land on `TrendsLineChart` (area is `fill` on the series; cumulative comes cumulated from the backend).
`ActionsStackedBar` normalizes to `ActionsBar` before it reaches the switch.
Bold number, table, world map, region map, and calendar heatmap are not quill charts.
Add a new display type there, with its own adapter directory under `products/product_analytics/frontend/insights/`.

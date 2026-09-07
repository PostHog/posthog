# Tooltips

Prefer the chart's built-in tooltip.
Built-in tooltips differ by chart; `DefaultTooltip` is not universal.
For example, [ScatterChart](../../../../packages/quill/packages/charts/src/charts/ScatterChart/ScatterChart.tsx) uses its own point tooltip.
Check the chart's types and [package tooltip docs](../../../../packages/quill/packages/charts/src/docs/tooltips.md) for supported options.

## Choose the smallest change

- Use `config.tooltip` for behavior and formatting that the chart supports.
  [buildSqlTooltipConfig](../../../../frontend/src/queries/nodes/DataVisualization/Components/Charts/sqlLineGraphAdapter.ts) shows per-column formatting for SQL series charts.
- Use a render prop only when those options cannot express the content.
- Use `DefaultTooltip` only when the context represents series rows at one label.
  Do not force point, funnel-step, or distribution data into that shape.
- A custom render prop owns its content formatting; pass formatters to that renderer.
  Keep supported behavior options in `config.tooltip`.
- For a different layout, use the package's tooltip pieces rather than custom panel styling.
  [FunnelStepTooltip](../../../../products/product_analytics/frontend/insights/funnels/shared/FunnelStepTooltip.tsx) uses `TooltipSurface` and `TooltipSwatch` for step details.

## Insight series

Use [InsightSeriesTooltip](../../../../products/product_analytics/frontend/insights/shared/InsightSeriesTooltip.tsx) when the chart needs insight series labels, aggregation formatting, or compare-period dates.
Build compatible metadata with [buildTrendsSeriesMeta](../../../../products/product_analytics/frontend/insights/trends/shared/trendsSeriesMeta.ts) for trends results.
Reuse its existing overrides for interval-count headers, lifecycle labels, and custom values before adding another tooltip.
Do not use it merely because a chart appears inside an insight.

For insight tooltips with clickable rows, use [INSIGHT_TOOLTIP_CONFIG](../../../../products/product_analytics/frontend/insights/shared/tooltipConfig.ts).
It enables pinning and cursor placement; pinning lets users click a row.
Follow [TrendsLineChart](../../../../products/product_analytics/frontend/insights/trends/TrendsLineChart/TrendsLineChart.tsx) for row-click routing and `footerOverride` when clicks open an insight instead of people.
Do not offer a drill-down hint when no action is available.
Do not add the legacy `InsightTooltip` to new charts.

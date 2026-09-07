# Insight chart integration

Use this reference when a chart consumes insight results or exposes an insight display type.
Start with [TrendsLineChart](../../../../products/product_analytics/frontend/insights/trends/TrendsLineChart/TrendsLineChart.tsx) or [TrendsBarChart](../../../../products/product_analytics/frontend/insights/trends/TrendsBarChart/TrendsBarChart.tsx).
Reuse the parts your chart needs.

## Display wiring

- Trends selects its chart in [Trends.tsx](../../../../frontend/src/scenes/trends/Trends.tsx).
  For a new display type, update that routing and the editor's display options.
  Use the corresponding family entry point for funnels or retention.
- Keep insight components under [product_analytics/frontend/insights](../../../../products/product_analytics/frontend/insights/).
- Reuse existing transforms before adding one.
  Shared MCP transforms must avoid kea and app-only imports (`lib/`, `scenes/`, and `~/`).
  [trendsChartDisplayOptions.ts](../../../../products/product_analytics/frontend/insights/trends/shared/trendsChartDisplayOptions.ts) defines dependency-neutral inputs.

## Results and axes

- Keep result IDs as series keys so legends and clicks can resolve the source result.
  Use [buildTrendsSeriesMeta](../../../../products/product_analytics/frontend/insights/trends/shared/trendsSeriesMeta.ts) when the tooltip needs trends metadata.
- Take the timezone and base currency from `teamLogic`, as the line chart does.
- Reuse [buildTrendsYAxisConfig](../../../../products/product_analytics/frontend/insights/trends/shared/trendsAxisFormat.ts) for aggregation formatting and range rules.
- Preserve magnitude grouping with [computeMagnitudeAxisIds](../../../../products/product_analytics/frontend/insights/trends/shared/magnitudeAxisIds.ts) when multiple axes are enabled.
- Preserve comparison dimming: [line transforms](../../../../products/product_analytics/frontend/insights/trends/TrendsLineChart/trendsChartTransforms.ts) use `comparisonOf`; [bar transforms](../../../../products/product_analytics/frontend/insights/trends/TrendsBarChart/trendsBarChartTransforms.ts) use `dimHexColor`.

## Legend visibility

- Use [useInsightsLegendConfig](../../../../products/product_analytics/frontend/insights/trends/shared/useInsightsLegendConfig.tsx) when visibility persists through `trendsDataLogic`.
  It keeps compare-period rows in one visibility group and disables editing in shared or non-editable views.
- Keep hidden series available through `hiddenKeys` so the legend can restore them.
  Aggregated bars instead remove hidden rows to avoid empty bands; follow the bar chart's existing branch.
- For chart-local visibility, use [buildBaseLegendConfig](../../../../products/product_analytics/frontend/insights/trends/shared/buildBaseLegendConfig.ts) with the existing series menu, or a plain legend config.

## Interactions and surrounding UI

- For actor drill-down or a host click handler, reuse [handleTrendsChartClick](../../../../products/product_analytics/frontend/insights/trends/shared/handleTrendsChartClick.tsx).
  It resolves the series key, prefers the host's click handler, and otherwise builds the persons query.
  Navigation-only fallbacks stay in the consumer; follow the line chart's existing branch.
- Use [useDateRangeZoom](../../../../frontend/src/lib/charts/hooks.ts) with result dates and the host's handler.
  It applies the rollout gate and emits bucket starts; the host expands the end bucket.
- Match tooltip row clicks and footer text to the actual destination; see [tooltips](./tooltips.md).
- Reuse [hasTrendsChartData](../../../../products/product_analytics/frontend/insights/shared/hasTrendsChartData.ts) and `InsightEmptyState` for empty insight results.
- Report chart errors through [makeChartErrorHandler](../../../../products/product_analytics/frontend/insights/trends/shared/chartErrorHandler.ts).
- For annotations, goal lines, and alerts, see [overlays](./overlays.md).
- Reuse existing coverage and add only cases needed for the change; see [testing and stories](./testing-and-stories.md).

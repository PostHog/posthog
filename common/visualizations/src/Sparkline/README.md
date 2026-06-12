# Sparkline

Compact, props-driven bar or line chart for inline metrics — the model citizen of this package: no kea logics, everything via props.

## Exports

- `Sparkline` (`Sparkline.tsx`) — key props (`SparklineProps`):
  - `data: number[] | SparklineTimeSeries[]` — a single muted series or multiple named series
  - `labels?: string[]`, `renderLabel?`, `renderTooltipValue?` — per-point labels and tooltip formatting
  - `type?: 'bar' | 'line'` (default `'bar'`), `color?`/`colors?` (names from `vars.scss`)
  - `maximumIndicator?` — show the Y-axis max (default `true`); `loading?` — render a skeleton
  - `withXScale?`/`withYScale?` — transform the generated scale options (`AnyScaleOptions`)
  - `referenceLines?: SparklineReferenceLine[]` — dashed horizontal threshold/goal lines with optional labels
  - `onSelectionChange?` — drag-to-select a label-index range; `highlightedRange?` — mirror an external selection as a translucent box
  - tooltip tuning: `tooltipRowCutoff?` (default 8), `hideZerosInTooltip?`, `sortTooltipByCount?`
- `SparklineTimeSeries`, `SparklineReferenceLine`, `AnyScaleOptions` — supporting types.

## Chart.js plugins

Imports `chartjs-plugin-annotation` and registers it once at module load (idempotent) for reference lines and the highlighted-range box.
The `Chart` class and types come from `@posthog/visualizations/Chart`.
Tooltips render an `InsightTooltip` inside a `Popover`.

## Consumers

Widely used across products, not tied to any query kind:

- `products/logs/` — log volume sparklines (viewer, services, sampling form, alert detail scene)
- `products/links/frontend/LinkMetricSparkline.tsx`, `products/tracing/frontend/TracingSparkline.tsx`, `products/metrics/frontend/components/MetricsViewer.tsx`
- `products/customer_analytics/frontend/components/UsageMetricCard.tsx`
- `frontend/src/lib/components/AppMetrics/AppMetricsSparkline.tsx`, `frontend/src/scenes/hog-functions/metrics/HogFunctionEventEstimates.tsx`
- `frontend/src/scenes/data-management/ingestion-warnings/IngestionWarningsView.tsx`
- `common/query-frontend/src/nodes/HogQLX/render.tsx` — `<Sparkline>` tags in HogQLX output

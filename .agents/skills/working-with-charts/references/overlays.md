# App overlays

Use the [package overlay docs](../../../../packages/quill/packages/charts/src/docs/overlays.md) for built-in components, layout hooks, positioning, and pointer behavior.
Reuse a built-in overlay or an existing app component before adding one.
Keep overlays that read kea, product types, or PostHog models in the app, next to their consumer.

## Insight overlays

- [AnnotationsLayer](../../../../frontend/src/lib/components/AnnotationsOverlay/AnnotationsLayer.tsx) places annotations on the chart's visible ticks.
  Pass result dates; grouped compare bars also need the current and previous series keys.
  Preserve the host's annotation visibility rules.
- [TrendsAlertOverlays](../../../../products/product_analytics/frontend/insights/trends/shared/TrendsAlertOverlays.tsx) renders alert thresholds and anomaly markers.
  Mount it only for saved insights, so it does not request unfiltered alerts.
  Pass each series' axis ID and hidden state to keep markers aligned with visible results.
- [goalLinesAdapter](../../../../products/product_analytics/frontend/insights/trends/shared/goalLinesAdapter.ts) maps saved goal lines into chart config or reference lines.
  Follow [TrendsBarChart](../../../../products/product_analytics/frontend/insights/trends/TrendsBarChart/TrendsBarChart.tsx) for its time-series and aggregated branches.
  The package docs explain when goal lines expand the axis range.

## Other source examples

- [BillingPeriodMarkers](../../../../frontend/src/scenes/billing/BillingPeriodMarkers.tsx): markers at dates between chart labels.
- [MetricsExemplarMarkers](../../../../products/metrics/frontend/components/MetricsExemplarMarkers.tsx): accessible buttons with their own tooltips.
  It uses `data-hog-charts-interactive-overlay` and stops click propagation so the chart does not also handle the interaction.
- [EventMarkers](../../../../products/error_tracking/frontend/components/VolumeSparkline/EventMarkers.tsx): labels above a sparkline, with space reserved in the chart margin.
- [DonutCenterLabel](../../../../products/product_analytics/frontend/insights/trends/TrendsPieChart/DonutCenterLabel.tsx): a pie-chart child using radial layout.

Keep derived-data choices in the existing chart transforms.
For example, [trendsChartTransforms](../../../../products/product_analytics/frontend/insights/trends/TrendsLineChart/trendsChartTransforms.ts) configures trend lines, moving averages, and confidence bands without custom app overlays.

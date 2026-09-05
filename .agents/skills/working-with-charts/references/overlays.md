# Overlays

An overlay is a React child of a chart.
It renders DOM (or SVG) on top of the canvas, positioned from the chart's scales.
The canvas draws the series, grid, axis lines, and hover highlight; everything a user reads as a label, line, badge, or marker is an overlay.

```tsx
<TimeSeriesLineChart series={series} labels={labels} theme={theme} config={config}>
  <ReferenceLines lines={goalLines} />
  <ValueLabels valueFormatter={formatValue} />
  <AnnotationsLayer insightNumericId={insight.id} dates={days} />
</TimeSeriesLineChart>
```

Reach for an existing overlay before writing one. Reach for a derived series before writing an overlay: trend lines, moving averages, and confidence bands are extra `Series` entries (`overlay: true` for the first two), not overlay components.

## Library overlays

`ReferenceLine` / `ReferenceLines`, `ValueLabels`, `AxisTitles`, `TrendLineOverlay`, `HighlightedRange`, and `AnomalyPointsLayer`, all exported from `@posthog/quill-charts`.
What each draws, its props, and its edge cases are in the library's [docs/overlays.md](../../../../packages/quill/packages/charts/src/docs/overlays.md).
The built-in legend and `DefaultTooltip` are not children: enable the legend with `config.legend` (see the legend section in SKILL.md) and see [tooltips.md](./tooltips.md) for the tooltip.

Goal lines on trends go through `config.goalLines` on the time-series wrappers (the chart stretches the axis to reach an off-scale target) or through `goalLinesToReferenceLines` + `<ReferenceLines>` on the base `BarChart`. Both live in `products/product_analytics/frontend/insights/trends/shared/goalLinesAdapter.ts`.

## App-owned overlays

These import kea, PostHog models, or product types, so they live next to their consumer, never in the library.
Copy their shape when you need something similar.

| Overlay                  | Path                                                                                      | What it shows and what it teaches                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ------------------------ | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AnnotationsLayer`       | `frontend/src/lib/components/AnnotationsOverlay/AnnotationsLayer.tsx`                     | Annotation badges under the x-axis for any insight chart. Reads `labels`, `scales.x(label, seriesKey)`, `dimensions`, and `axis.xTickFormatter` from `useChartLayout()`; uses `computeVisibleXLabels` so badges group on the same ticks the axis draws. Passes `seriesKey` / `previousSeriesKey` so grouped compare bars anchor each period on its own bar. Re-enables `pointer-events` and stops mouse propagation so badges do not move the crosshair. |
| `TrendsAlertOverlays`    | `products/product_analytics/frontend/insights/trends/shared/TrendsAlertOverlays.tsx`      | Alert thresholds as `ReferenceLines` (variant `alert`) plus `AnomalyPointsLayer` markers. Lifted into its own component so `insightAlertsLogic` only mounts for saved insights. Takes `getYAxisId` so a marker reads the same axis its series is scaled on.                                                                                                                                                                                              |
| `BillingPeriodMarkers`   | `frontend/src/scenes/billing/BillingPeriodMarkers.tsx`                                    | Dashed vertical lines at dates that fall _between_ labels. Interpolates x between the two bracketing labels because `ReferenceLine` can only sit on a label. The label sits above the plot so the chart's own tooltip drops while it is hovered.                                                                                                                                                                                                         |
| `MetricsExemplarMarkers` | `products/metrics/frontend/components/MetricsExemplarMarkers.tsx`                         | Clickable dots on the baseline, each with its own Lemon `Tooltip`. Marks the button with `data-hog-charts-interactive-overlay` so the chart's hover tracking ignores it, and calls `stopPropagation` on click so `onPointClick` does not fire.                                                                                                                                                                                                           |
| `EventMarkers`           | `products/error_tracking/frontend/components/VolumeSparkline/EventMarkers.tsx`            | Pills with connectors above a sparkline, spread apart after measuring their widths. Wrapped in `memo` because it renders inside the chart host. Reserves top margin through the chart's `config.margins` so pills do not overlap bars.                                                                                                                                                                                                                   |
| `DonutCenterLabel`       | `products/product_analytics/frontend/insights/trends/TrendsPieChart/DonutCenterLabel.tsx` | Radial chart overlay; reads `useRadialLayout()` rather than `useChartLayout()`.                                                                                                                                                                                                                                                                                                                                                                          |

## Writing a new overlay

Decide where it lives first.

- Generic, app-agnostic, and reusable by another host (a range box, a marker layer keyed on index and value): add it to `packages/quill/packages/charts/src/overlays/`, export it from `src/index.ts`, add a story next to it, add a `data-attr` and an accessor method in `src/testing/accessor.ts`, and update the library's `src/docs/overlays.md` in the same PR.
- Anything that reads kea, PostHog models, product types, or app copy: keep it next to its consumer, in the product's `frontend/` or the shared `lib/components/` if two products need it.

The hooks, the positioning rules, and a minimal example are in the library's [docs/overlays.md](../../../../packages/quill/packages/charts/src/docs/overlays.md) under "Custom overlays".
On top of those, copy the app precedent closest to your case: `BillingPeriodMarkers` for a position between labels, `MetricsExemplarMarkers` for a clickable marker, `EventMarkers` for reserving headroom through `config.margins`, and `AnnotationsLayer` for lining up with the ticks the axis drew.

If the thing you want is a series (a projection, an average, a band, a goal that should stretch the axis), make it a series and stop.

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

All exported from `@posthog/quill-charts`. Behavior details live in the library's [docs/overlays.md](../../../../packages/quill/packages/charts/src/docs/overlays.md); prop lists are the JSDoc on each component's props.

| Overlay                            | Draws                                                           | Notes                                                                                                                                                                                                                                                   |
| ---------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ReferenceLine` / `ReferenceLines` | A horizontal or vertical line at a value or label, with a label | Variants `goal` (dashed grey), `alert` (dashed red), `marker` (solid thin). Hides itself when its value falls outside a pinned axis range. Vertical lines resolve x through `scales.x(label)`, so they can only sit on a label.                         |
| `ValueLabels`                      | The value of each point or bar segment next to it               | Formatter gets `(value, seriesIndex, dataIndex, context)`. In percent layouts `value` is a 0..1 fraction; `context.rawValue` holds the original. `mode="stack-total"` labels the stack top only. Per-series opt-out via `series.visibility.valueLabel`. |
| `AxisTitles`                       | Axis titles in each axis gutter                                 | The time-series wrappers render this for you from `xAxis.label` / `yAxis.label`. Compose it yourself only on the base charts.                                                                                                                           |
| `TrendLineOverlay`                 | Linear or exponential regression lines as SVG polylines         | Vertical bar and combo charts only. Prefer `config.trendLines` on the time-series wrappers, which build and pass it for you.                                                                                                                            |
| `HighlightedRange`                 | A translucent box across an x range                             | `start` / `end` as indices or labels, straight from `onDateRangeZoom`. Mirrors an external selection (a paired list's visible rows, a picked window) onto the chart.                                                                                    |
| `AnomalyPointsLayer`               | Small filled dots at `{ dataIndex, value, yAxisId, color }`     | DOM rather than a series, because a sparse series would make the line renderer bridge the gaps. Trends uses it for alert anomalies.                                                                                                                     |
| Built-in legend                    | Rows with swatch, label, isolate/toggle behavior                | Not a child. Enable with `config.legend: { show: true, ... }`. See the legend section in SKILL.md.                                                                                                                                                      |
| `DefaultTooltip`                   | The hover tooltip                                               | Not a child either; see [tooltips.md](./tooltips.md).                                                                                                                                                                                                   |

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

Then follow this shape:

```tsx
import { useChartLayout } from '@posthog/quill-charts'

export function GoalBadge({ value }: { value: number }): JSX.Element | null {
  const { scales, dimensions, labels, theme } = useChartLayout()
  const y = scales.y(value)
  const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
  if (!isFinite(y) || y < plotTop || y > plotTop + plotHeight) {
    return null
  }
  return (
    <div
      data-attr="goal-badge"
      className="absolute pointer-events-none text-xs"
      style={{ left: plotLeft + plotWidth, top: y }}
    >
      Goal
    </div>
  )
}
```

Rules that keep an overlay correct and cheap:

- **Pick the hook by what you read.** `useChartLayout()` gives `scales`, `dimensions`, `labels`, `series`, `theme`, `axis`, `yGutters`, `resolvePositionValue`, `canvasBounds()` and does not re-render on hover. `useChartHover()` gives `hoverIndex` and re-renders on every mousemove. `useChart()` merges both; use it only when you need both.
- **Position from the scales, never from your own math.** `scales.x(label, seriesKey?)` for x, `scales.y(value)` or `scales.yAxes[id].scale(value)` for y on multi-axis charts. `scales.extent(label)` gives the band width on bar charts. `resolvePositionValue(seriesIndex, dataIndex)` gives the stacked top when the chart stacks.
- **Between-label positions need interpolation.** Band and point scales only resolve whole labels. When a timestamp falls between buckets, interpolate between the two labels that bracket it, as `BillingPeriodMarkers` and `MetricsExemplarMarkers` do.
- **Hide what falls outside the plot.** Check against `dimensions.plotLeft/Top/Width/Height` and return null, so a pinned axis range does not push a marker over the axis chrome.
- **Static styling in Tailwind classes; only computed pixels and runtime colors inline.** `theme.backgroundColor` blends borders into the chart surface; `theme.axisLineColor` matches the axis chrome.
- **Overlays are `pointer-events: none` by default.** Opt back in with `pointer-events-auto` only on the element the user interacts with.
- **Interactive elements mark themselves.** Put `data-hog-charts-interactive-overlay` on the interactive root so the chart's hover tracking ignores it, and `stopPropagation` on click so `onPointClick` does not also fire. Without the attribute the chart's nearest-point tooltip fights the overlay's tooltip for the cursor.
- **Add a `data-attr`** so tests can find it through the DOM.
- **Memoize the inputs.** The overlay re-renders whenever the chart lays out; anything computed from `labels` or `scales.x` goes in a `useMemo` keyed on `scales.x`, not on `scales`.
- **Use `computeVisibleXLabels(labels, scales.x, axis.xTickFormatter)`** when the overlay must line up with the ticks the axis actually drew.

If the thing you want is a series (a projection, an average, a band, a goal that should stretch the axis), make it a series and stop.

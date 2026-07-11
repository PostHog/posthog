# Work stream: replace experiments Chart.js charts with quill

Goal: remove Chart.js from `frontend/src/scenes/experiments/`.
Part of the chart.js removal effort — see [quill-chart-migration.md](./quill-chart-migration.md).

## Scope — exactly two Chart.js consumers

1. `ExperimentView/Exposures.tsx` — two `useChart` components: `MicroChart` (60×20 inline multi-variant sparkline in the collapse header) and `ExposuresChart` (full-size per-variant exposure lines)
2. `MetricsView/new/VariantTimeseriesChart.tsx` (+ dataset construction in `experimentTimeseriesLogic.ts`, tooltip in `VariantTimeseriesTooltip.tsx`, consumer `TimeseriesModal.tsx`) — single-variant daily delta line with a confidence-interval ribbon

**Out of scope** (not Chart.js, despite grep hits): `MetricsView/new/ChartCell.tsx` / `ChartGradients.tsx` (custom SVG violin plots), the frozen `legacy/metricsView/` tree (`@deprecated`, "do not modify" — deleted with legacy experiments), `MetricsView/shared/colors.ts` (color hook only).
`RecalculationStatus.tsx` already imports from `@posthog/quill-charts`, so the dependency is wired into this scene.

## Rollout context — important

The new metrics view (containing both targets) is **not** behind a feature flag; it is the live default for all non-legacy experiments (`ExperimentView.tsx` gates the legacy path, not this one).
Add a temporary flag for this migration (follow the `EXPERIMENTS_METRICS_RECALCULATION` pattern) rather than shipping unconditionally.

## Part 1 — ExposuresChart (do first, lowest risk)

Current: one Chart.js line per variant (cumulative exposures/day), `getSeriesColor(index)`, `beginAtZero`, grid on, legend configured-but-hidden, **default built-in Chart.js tooltip** (never customized), no click handlers.

Target: `TimeSeriesLineChart`:

- `series`: one per variant, `key`/`label` = variant, explicit `color` via `getSeriesColor(index)`
- `config.xAxis = { timezone, interval: 'day' }`; y `startAtZero` (default)
- `config.legend: { show: false }`; drop the dead Chart.js legend styling keys
- Tooltip is an upgrade, not a port: use `DefaultTooltip` via `config.tooltip` with a count formatter
- The synthetic-prior-day padding for single-day data (`buildExposureDatasets`) is data-prep and carries over unchanged

## Part 2 — MicroChart

Quill `Sparkline` is single-series, so the current single-canvas multi-variant overlay has no 1:1 swap.
Decide between: (a) a compact `LineChart` with hidden axes (`hideXAxis`/`hideYAxis`, no tooltip) keeping the overlaid-variants look — closest to today, or (b) one quill `Sparkline` per variant — a layout change.
Recommend (a).

## Part 3 — VariantTimeseriesChart (the hard one)

Current Chart.js construction (`experimentTimeseriesLogic.ts` `chartData` selector): three datasets —

1. CI upper bound (thin line)
2. CI lower bound with `fill: '-1'` (the ribbon) and a **per-segment `backgroundColor`** callback: green/red tint when that day is `significant`, gray otherwise
3. Delta line with **per-segment dash + dim** for segments leading into interpolated (`!hasRealData`, carried-forward) points, and **per-point dimmed markers** for those points

Plus: percent y-ticks, a forced zero tick with padded axis min and a bolded zero gridline, 45° x labels, and a rich portal tooltip (`VariantTimeseriesTooltip`: delta, CI, exposures, significance, interpolation warning, timezone block).

Target: `TimeSeriesLineChart` + `config.confidenceIntervals` (the `{seriesKey, lower, upper}` consumption shape; precedent: `TrendsLineChart.tsx` + `trendsChartTransforms.ts`).
The tooltip ports cleanly: pass `VariantTimeseriesTooltip` as the `tooltip` render prop and delete the `useInsightTooltip` portal plumbing.
Zero line: `ReferenceLine` at 0 (marker variant) + y-domain tuning.

**Blocking design decisions — settle these before implementing, they are quill API questions, not implementation details:**

| Legacy behavior | Quill today | Options |
| --- | --- | --- |
| CI band color per day (significance) | one `color`/`opacity` per band | (a) extend quill fill with per-index color, (b) split the band into contiguous same-color run series (visual seams), (c) accept a single neutral band color |
| Dashed segments for each interpolated run (can be multiple disjoint runs) | `Series.stroke.partial` = one contiguous range | (a) extend `stroke.partial` to accept multiple ranges / a per-index predicate, (b) accept a single dashed tail only |
| Dimmed per-point markers for interpolated points | `Series.points` has a single static radius/color | (a) per-point style hook in quill, (b) custom overlay child, (c) drop and rely on the tooltip's interpolation warning |

If extending quill, remember its `AGENTS.md` must be updated in the same PR.
If scoping down (options b/c), get a design/product sign-off first — the significance tinting is meaningful UX, not decoration.

## Suggested PR sequence

1. Flag + `ExposuresChart` → quill (self-contained, exercises the scene end to end)
2. `MicroChart` (small; bundle with 1 if the compact-`LineChart` route is chosen)
3. Quill capability PR(s) per the decisions above (if extending)
4. `VariantTimeseriesChart` + `experimentTimeseriesLogic` rewrite (dataset construction becomes quill `series`/`confidenceIntervals` builders — the trimming/carry-forward logic is data-prep and survives unchanged)
5. Remove the flag, drop `lib/Chart` imports from `scenes/experiments/`

## Testing

No unit tests or stories exist for any of these components today; existing experiment stories exercise them only incidentally via full-page snapshots.
Add net-new tests with `@posthog/quill-charts/testing` (invoke `/writing-tests`): CI band series derivation from backend `lower_bound`/`upper_bound` (including trimming and carry-forward flags), exposure series construction (single-day padding), and tooltip content for interpolated vs real points.

# Work stream: replace BillingLineGraph with quill

Goal: delete `frontend/src/scenes/billing/BillingLineGraph.tsx`, `BillingLineGraphTooltip.tsx`, and `useBillingMarkersPositioning.ts` (Chart.js + `chartjs-plugin-annotation`, ~500 lines) in favor of quill `TimeSeriesLineChart`.
Part of the chart.js removal effort — see [quill-chart-migration.md](./quill-chart-migration.md).

## Current behavior to preserve

`BillingLineGraph` renders a multi-series line chart of billing usage or spend:

- One `ChartDataset<'line'>` per `BillingSeriesType { id, label, data, dates }`; shared `dates: string[]` as labels; colors via `getSeriesColor(id % 15)`
- Time x-axis (`unit: day|week|month`, ticks pinned to labels), y-axis `beginAtZero` with `valueFormatter` ticks (plain numbers for usage, USD currency for spend)
- `tension: 0.1`, `pointRadius: 0` / `pointHoverRadius: 4`
- Custom external React tooltip (`BillingLineGraphTooltip`): rows sorted descending by value, color dot + label + formatted value, viewport-flip positioning
- **Billing period markers**: vertical dashed lines at period-boundary dates (annotation plugin); only the most recent visible marker gets a floating "New billing period" HTML label with an info icon + rich hover `Tooltip`
- `useBillingMarkersPositioning` + `chartReady`/`stableChartAreaLeft` debounce machinery exists solely to pixel-position that label against the live Chart.js instance
- Legend: both consumers pass `showLegend={false}` — `BillingDataTable`'s checkbox rows are the de facto legend and drive `hiddenSeries` (parent filters series before passing them in)
- `isLoading` renders a dimmed overlay; empty state handled outside the component (`BillingEmptyState`)

Consumers: `BillingUsage.tsx:212` and `BillingSpendView.tsx:214` (identical layout: filters → graph → `BillingDataTable`).
Markers come from `calculateBillingPeriodMarkers` in `billing-utils.ts:533`.

## Quill mapping

| Legacy | Quill |
| --- | --- |
| Multi-series line datasets | `TimeSeriesLineChart` `series: Series[]` (`key: String(id)`) |
| Time axis + interval | `labels` + `config.xAxis = { timezone: 'UTC', interval }` |
| Y formatting | `config.yAxis.format: 'numeric'` (usage) / `'currency', currency: 'USD'` (spend); `startAtZero` default matches `beginAtZero` |
| External tooltip | `DefaultTooltip` via `config.tooltip = { sortedByValue: true, valueFormatter }` — delete the portal/positioning machinery entirely |
| Period marker lines | `ReferenceLine orientation="vertical"` children with dashed `style`; `value` must exactly match an entry in `labels` (format markers with the same string format as `dates`) |
| Legend off + external toggles | `config.legend: { show: false }` (default); keep the parent-filters-`hiddenSeries` pattern unchanged |
| `useBillingMarkersPositioning` + ready/debounce state | delete — a custom overlay child reads `useChartLayout()` scales synchronously |
| Dark mode recompute (`getGraphColors`/`isDarkModeOn`) | delete — `useChartTheme()` from `frontend/src/lib/charts/hooks.ts` tracks it |

## Known gaps / decisions

1. **Rich marker label** — `ReferenceLine`'s built-in `label` is plain text; the "New billing period" label needs its icon + bulleted hover `Tooltip`. Build a small custom overlay child positioned via `useChartLayout()` (this replaces, and is much simpler than, `useBillingMarkersPositioning`). Keep the existing "only the latest visible marker gets the label" rule (`.slice(-1)`) in the adapter.
2. **Color alignment with `BillingDataTable`** — the table's row ribbons use `getSeriesColor(id % 15)`. Pass `color` explicitly per series to quill (same function) so chart lines and table ribbons stay identical; don't rely on quill's index-based palette (index ≠ id once series are hidden).
3. **Curve** — quill offers `linear` or `monotone` only; `tension: 0.1` has no exact equivalent. Use whatever `useChartConfig()` from `lib/charts/hooks.ts` yields so billing matches the app-wide style (the `QUILL_CHART_STYLE_REFRESH` flag applies automatically).
4. **Hover point radius** — verify quill's hover overlay covers the `pointHoverRadius: 4` behavior; `Series.points` only takes a static radius.
5. **Dead code** — `frontend/src/scenes/billing/BillingTooltip.tsx` is an unused near-duplicate of `BillingLineGraphTooltip.tsx`; delete it in this work stream rather than porting it.
6. `BillingSeriesType` and `SeriesColorDot` are imported by `BillingDataTable.tsx` — move them (e.g. to a `billing` types/util module) before deleting `BillingLineGraph.tsx`.

## Suggested PR sequence

1. Single PR is feasible: new quill-based `BillingLineGraph` (same props: `series`, `dates`, `isLoading`, `interval`, `billingPeriodMarkers`), marker overlay child, consumers unchanged.
   Billing is a sensitive, money-adjacent surface — gate with a short-lived flag if visual parity is uncertain, otherwise ship directly given the component's small consumer count.
2. Follow-up cleanup: delete legacy files + `BillingTooltip.tsx`, drop the annotation-plugin registration if billing was its last core-app user (alerts product also registers it — check before removing the dependency).

## Testing

No tests or stories exist today for any of these files, so add net-new coverage (invoke `/writing-tests`):

- Marker `ReferenceLine`s render at the correct x for given `billingPeriodMarkers`, and only the latest visible marker gets the explanatory label
- Tooltip rows sorted descending with currency vs numeric formatting (use `@posthog/quill-charts/testing` `getHogChart` / tooltip accessors)
- A story each for the usage and spend variants

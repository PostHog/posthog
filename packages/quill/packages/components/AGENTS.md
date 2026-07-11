# Components — Agent Reference

Quick-reference for AI agents using `@posthog/quill-components` — composed components built on quill primitives. For primitive-level guidance (choosing a component, spacing, the `render` prop), read `../primitives/AGENTS.md` first.

## Exports

- `DataTable` — TanStack Table wired onto quill `Table` + `Pagination`
- `DateTimePicker` — calendar range picker with quick-range presets (`quickRanges`, `CUSTOM_RANGE`)
- `DatePicker` — single-date picker (one calendar, optional time, no quick ranges)
- `useCalendar` — headless calendar grid hook (`Day`, `Month` enums)
- `Metric` — composable stat tile (`Card` + `Badge` pill + `Sparkline`); marries primitives with `@posthog/quill-charts`. Import from the `@posthog/quill-components/metric` subpath (not the main barrel)

## DataTable

```tsx
import { type ColumnDef } from '@tanstack/react-table'
import { DataTable } from '@posthog/quill-components'

const columns: ColumnDef<Person>[] = [
  { accessorKey: 'name', header: 'Name', meta: { expand: true } },
  { accessorKey: 'status', header: 'Status', meta: { align: 'center' } },
  { accessorKey: 'amount', header: 'Amount', meta: { align: 'right' }, enableSorting: false },
]

<DataTable
  columns={columns}
  data={data}
  pageSize={10}                  // omit for an unpaginated table
  pageSizeOptions={[10, 25, 50]} // renders the per-page selector
  stickyHeader                   // or "page" to stick to document scroll
  fullWidth
  size="sm"                      // tighten cell padding; pair with Card size="sm"
/>
```

Rules:

- Column defs are standard TanStack `ColumnDef`s; quill-specific options go in `meta`: `align: 'left' | 'center' | 'right'` (header + cells) and `expand: true` (absorb leftover width).
- `fullWidth` needs exactly one column with `meta: { expand: true }` to decide which column stretches.
- Sorting is client-side and on by default — click header toggles asc → desc → off. Opt out per column with `enableSorting: false`.
- Pagination is opt-in via `pageSize`; the component owns page state and resets to page 0 when `pageSize` changes. The pager is suppressed when the table has no rows — an empty table shows only its empty state, never a "0–0 of 0" pager.
- Custom empty state via the `empty` prop (ReactNode); default is a minimal "No results".
- Don't rebuild tables from `Table` primitives when the data is row/column shaped and needs sorting or pagination — that's what DataTable is for. Drop to the `Table` primitive only for fully custom layouts.

## DateTimePicker

```tsx
import { CUSTOM_RANGE, DateTimePicker, quickRanges } from '@posthog/quill-components'
;<DateTimePicker
  value={{ start, end, range: CUSTOM_RANGE }}
  onApply={(value) => setRange(value)}
  onCancel={() => close()}
  minDate={minDate}
  maxDate={new Date()}
  dateFormat="MDY" // or 'DMY' | 'YMD'
  compact // single calendar + horizontal quick ranges
/>
```

Rules:

- `value.range` is one of `quickRanges` (15 presets, "Last 5 minutes" → "Last 1 year") or `CUSTOM_RANGE` for manual selection.
- Changes are staged until `onApply` fires — don't treat intermediate calendar clicks as committed.
- Dual-calendar layout appears at the `lg` breakpoint unless `compact` forces a single calendar.
- `minDate`/`maxDate` are day-granular; time inputs are independent of those bounds.
- `weekStartsOn` affects the calendar grid only, not quick-range math.

## DatePicker

Single-date sibling of `DateTimePicker` — one calendar, no quick ranges, value is a plain `Date`.

```tsx
import { DatePicker } from '@posthog/quill-components'
;<DatePicker
  value={date}
  onApply={(next) => setDate(next)}
  onCancel={() => close()}
  minDate={minDate}
  maxDate={new Date()}
  dateFormat="MDY" // or 'DMY' | 'YMD'
  showTime // include time in the value initially (hour/minute inputs shown)
  showTimeToggle // render the "Include time" toggle; defaults to showTime. false = fixed precision
  onIncludeTimeChange={(includeTime) => ...} // fired when the toggle flips
/>
```

Rules:

- `value`/`onApply` are a single `Date`, not `{ start, end, range }`. Use this for the single-date PostHog callers (currently `LemonCalendarSelect`); reach for `DateTimePicker` only when you need a start→end range.
- `showTime` seeds whether time is included; `showTimeToggle` (defaults to `showTime`) decides whether the "Include time" toggle renders. Set `showTimeToggle={false}` with `showTime` for a fixed time precision (no opt-out); pass `showTimeToggle` alone to start date-only but let the user add time. `onIncludeTimeChange` reports toggle changes so a wrapper can mirror the state (e.g. to update a trigger label).
- Without time included the applied value is floored to start-of-day; with it, the value keeps its hour/minute.
- Shares the calendar grid and `minDate`/`maxDate` day-granular bounds with `DateTimePicker` (both render `Calendar` from `calendar-grid.tsx`).
- Always a single calendar; there is no `compact`/dual-calendar mode.

## useCalendar

Headless month-grid state for building custom calendar UIs: returns `calendar` (months > weeks > days), view navigation (`viewNextMonth`, `viewToday`, ...), and selection helpers (`select`, `selectRange`, `isSelected`, `toggle`). Selected dates are normalized to midnight. Reach for this only when DateTimePicker doesn't fit.

## Metric

A composable stat tile: a headline number, a `Badge` change pill, and an optional `Sparkline`. `Metric` is **content, not a surface** — wrap it in `<Card flush>` for the border. It's the one component here that depends on `@posthog/quill-charts` (for `Sparkline` + the headless metric math), which pulls d3 — so it lives behind its own `@posthog/quill-components/metric` entry point, **not** the main barrel (and not the `@posthog/quill` umbrella). That keeps charts/d3 out of the always-eager app-shell graph: only code that imports the metric subpath pays for it. The `MetricCard` in `@posthog/quill-charts` is the older, self-contained (prop-driven, primitives-free) tile; use `Metric` when you want to compose the layout or lean on quill's `Card`/`Badge`.

```tsx
import {
  Metric,
  MetricHeader,
  MetricTitle,
  MetricDelta,
  MetricValue,
  MetricSubtitle,
  MetricSparkline,
} from '@posthog/quill-components/metric'
import { Card } from '@posthog/quill-primitives'
import { useChartTheme } from '@posthog/quill-charts'

const theme = useChartTheme()
;<Card flush className="h-40">
  <Metric data={series} labels={labels} theme={theme} color="#22d3ee" sparklineFill>
    <MetricHeader>
      <MetricTitle>Total revenue</MetricTitle>
      <MetricDelta /> {/* Badge: success/destructive by goodDirection; hidden when there's no delta */}
    </MetricHeader>
    <MetricValue className="mt-2" /> {/* hover-following headline; pass a text-* class to resize */}
    <MetricSubtitle className="mt-1" />
    <MetricSparkline /> {/* bleeds to the card's left/right; `<Card flush>` lets it reach the bottom */}
  </Metric>
</Card>
```

Rules:

- Wrap `Metric` in `<Card flush>` — `Metric` is just the layout/content (it owns its inline padding like `CardContent`, so the sparkline can bleed out with `-mx-4`); the card owns the border, block padding, and bottom edge. `flush` drops the card's bottom padding so `MetricSparkline` reaches the bottom; a number-only tile can use a plain `<Card>`.
- `MetricSparkline` owns the bottom-edge alignment (a built-in 6px shift that pushes the canvas's hover-ring margin past the card edge so the line rests on it) — a custom `className` only manages margins (`-mx-*`/`-mb-*`/`mt-*`), never re-adds the offset.
- Give the card a height (`className="h-40"`, or `h-full` in a sized box) when using `sparklineFill` or when you want a fixed-height sparkline pinned to the bottom; otherwise it sizes to content (`Metric` is `h-full` so it fills whatever card it's in).
- The root owns the data/hover behavior and feeds the parts via context — a part used outside `<Metric>` throws. Pass `value` for a number-only tile; pass `data`+`labels`+`theme` for a sparkline.
- `MetricDelta` renders a `Badge`; `goodDirection` (default `up`) decides success vs destructive. It carries its own `TooltipProvider`, so `changeTooltip` needs no app-root setup. resize via `className` (the metric insight passes its own larger-pill classes and puts it inline next to the headline via `MetricHeader`; there is no `changeInline` or size prop, compose and style at the call site).
- Reproduces `MetricCard`'s behavior (`restingSubtitle`, `hoverChangeFromPreviousPoint`, `changeTooltip`, `positiveColor`/`negativeColor` for user-configured pill colors); omit the color props to keep the semantic `Badge` variants.

## Maintenance

When adding or changing a component here, update this guide in the same PR and add a story next to the component.

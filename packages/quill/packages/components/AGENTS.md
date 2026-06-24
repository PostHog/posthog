# Components — Agent Reference

Quick-reference for AI agents using `@posthog/quill-components` — composed components built on quill primitives. For primitive-level guidance (choosing a component, spacing, the `render` prop), read `../primitives/AGENTS.md` first.

## Exports

- `DataTable` — TanStack Table wired onto quill `Table` + `Pagination`
- `DateTimePicker` — calendar range picker with quick-range presets (`quickRanges`, `CUSTOM_RANGE`)
- `DatePicker` — single-date picker (one calendar, optional time, no quick ranges)
- `useCalendar` — headless calendar grid hook (`Day`, `Month` enums)

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

## Maintenance

When adding or changing a component here, update this guide in the same PR and add a story next to the component.

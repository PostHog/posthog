# Components — Agent Reference

Quick-reference for AI agents using `@posthog/quill-components` — composed components built on quill primitives. For primitive-level guidance (choosing a component, spacing, the `render` prop), read `../primitives/AGENTS.md` first.

## Exports

- `DataTable` — TanStack Table wired onto quill `Table` + `Pagination`
- `DateTimePicker` — calendar range picker with quick-range presets (`quickRanges`, `CUSTOM_RANGE`)
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
/>
```

Rules:

- Column defs are standard TanStack `ColumnDef`s; quill-specific options go in `meta`: `align: 'left' | 'center' | 'right'` (header + cells) and `expand: true` (absorb leftover width).
- `fullWidth` needs exactly one column with `meta: { expand: true }` to decide which column stretches.
- Sorting is client-side and on by default — click header toggles asc → desc → off. Opt out per column with `enableSorting: false`.
- Pagination is opt-in via `pageSize`; the component owns page state and resets to page 0 when `pageSize` changes.
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

## useCalendar

Headless month-grid state for building custom calendar UIs: returns `calendar` (months > weeks > days), view navigation (`viewNextMonth`, `viewToday`, ...), and selection helpers (`select`, `selectRange`, `isSelected`, `toggle`). Selected dates are normalized to midnight. Reach for this only when DateTimePicker doesn't fit.

## Maintenance

When adding or changing a component here, update this guide in the same PR and add a story next to the component.

# Components — Agent Reference

Quick-reference for AI agents using `@posthog/quill-components` — composed components built on quill primitives. For primitive-level guidance (choosing a component, spacing, the `render` prop), read `../primitives/AGENTS.md` first.

## Exports

- `DataTable` — TanStack Table wired onto quill `Table` + `Pagination`, with an opt-in `selectable` checkbox variant
- `FilterMenuTrigger`, `FilterRadioSubMenu`, `FilterCheckboxSubMenu`, `FilterSearchSubMenu`, `FilterSubMenu`, `FilterClearItem`, `filterSummary` — the parts of a list's one filter menu
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
  onPageChange={(page, nextPage) => track(page, nextPage)} // one-based page numbers
  onRowClick={(row) => open(row)} // ignores links, buttons, and form controls inside the row
  selectable                     // checkbox column; shift-click selects a range
  getRowId={(row) => row.id}
  rowSelection={rowSelection}    // { [rowId]: true }
  onRowSelectionChange={setRowSelection}
/>
```

Rules:

- Column defs are standard TanStack `ColumnDef`s; quill-specific options go in `meta`: `align: 'left' | 'center' | 'right'` (header + cells), `expand: true` (absorb leftover width) and `sticky: 'left' | 'right'` (freeze the column while the table scrolls sideways, such as a name column beside a wide timeline).
- A row can grow to show more without an expansion API: render the extra content inside its cells from your own expanded state, toggled by `onRowClick`. Every cell in the row grows together, so a sticky label column stays aligned with the content beside it.
- `fullWidth` needs exactly one column with `meta: { expand: true }` to decide which column stretches.
- Sorting is client-side and on by default — click header toggles asc → desc → off. Opt out per column with `enableSorting: false`. A column needs an `accessorKey` or `accessorFn` to sort.
- A list sorted on the server passes `sorting` and `onSortingChange`. The table then keeps the rows in the order of `data`, only reports the clicks, and has no "off" state. Use `sortDescFirst` on a column to start at desc. `meta: { sortDataAttr }` sets the `data-attr` of the column's sort button.
- `resizableColumns` lets the user drag a column's edge, or focus it and use the arrow keys. Its line shows while the header is hovered, and its handle while that header cell is. Columns fit their content until the first resize, then stay fixed. Bound a column with `minSize` and `maxSize` (the default minimum is 64px), and opt it out with `enableResizing: false`, as an actions column should. `columnSizing` and `onColumnSizingChange` control the widths, in pixels by column id, so a caller can save and restore them. A drag never renders: the handle moves the column in the DOM and `onColumnSizingChange` fires once, when it ends, so a table of any size stays smooth. A double click on an edge resets that column. A resize changes the dragged column and no other, including an `expand` column, which stops stretching at the first resize. A `fullWidth` table fills any space left over with an empty column, and scrolls once the columns no longer fit. Touch screens have no resizing.
- `viewportRef` reaches the scrolling viewport, and `viewportEndRef` a marker at the end of it. Observe the marker, with the viewport as the root, to load more rows near the end.
- Pagination is opt-in via `pageSize`; the component owns page state, reports user navigation through `onPageChange`, and resets to page 0 when `pageSize` changes. The pager is suppressed when the table has no rows — an empty table shows only its empty state, never a "0–0 of 0" pager.
- Custom empty state via the `empty` prop (ReactNode); default is a minimal "No results".
- `rowClassName` accepts a class string or a function of the row data to style matching rows.
- `onRowClick` makes non-interactive parts of each row clickable and keyboard accessible. Links, buttons, form controls, editable content, and custom controls keep their own behavior. Add `data-row-click-ignore` to a custom descendant that must not activate the row.
- `selectable` is the selection variant: it adds a leading checkbox column, marks each selected row with `data-state="selected"`, and gives the header a checkbox that selects or clears every selectable row on the page. Shift-click a second checkbox to set every row between it and the one clicked last to the clicked row's new state, as LemonTable's `bulkSelection` does. To disable some rows, pass `rowSelectionDisabledReason`: a reason disables the row's checkbox and shows in its tooltip, `null` keeps the row selectable, and a shift-click range skips the disabled rows. `rowSelection` and `onRowSelectionChange` control the selection, as `{ [rowId]: true }`. Pass `getRowId` so the selection follows rows across a re-sort or a newly loaded page, and `rowSelectionLabel` to name each checkbox for screen readers. Put the bulk actions outside the table, shown while anything is selected, and clear the selection when the filters change.
- Don't rebuild tables from `Table` primitives when the data is row/column shaped and needs sorting or pagination — that's what DataTable is for. Drop to the `Table` primitive only for fully custom layouts.

## FilterMenu

A list's sort, filters and display choices live in one `DropdownMenu`, opened by a funnel button beside its search field.

```tsx
<DropdownMenu>
  <FilterMenuTrigger active={active} dataAttr="my-list-filter" />
  <DropdownMenuContent align="start" className="min-w-64">
    <FilterRadioSubMenu label="Sort by" options={sorts} value={sort} onChange={setSort} />
    <DropdownMenuSeparator />
    <FilterCheckboxSubMenu
      label="Type"
      allLabel="All types"
      pluralNoun="types"
      options={types}
      selected={picked}
      onChange={setPicked}
    />
    <FilterSearchSubMenu
      label="Tags"
      allLabel="Any tag"
      pluralNoun="tags"
      options={tags}
      selected={tagged}
      onChange={setTagged}
      searchPlaceholder="Search tags"
      emptyText="No tag matches"
    />
    <FilterClearItem active={active} onClear={clear} />
  </DropdownMenuContent>
</DropdownMenu>
```

Rules:

- One choice → `FilterRadioSubMenu`. Several from a short list → `FilterCheckboxSubMenu`. Several from a long list → `FilterSearchSubMenu`.
- An empty selection means all of them. Pass `defaultValue` on a radio filter so that a change takes the primary color. Leave it out on a row that isn't a filter, such as a sort.
- To measure a long list, pass `onOpened` to `FilterSearchSubMenu`. It reports how long the submenu took to paint and how many options it listed, because every row stays mounted.
- A list too long to load whole, such as a project's tags, searches on the server. Pass `onSearchChange` to get the search text, `onScrollEnd` to load the next page, and `onClose` to drop the pages, and give `options` only the page loaded so far.
- `active` covers filters only. A sort, a display choice or the search text never lights the dot.

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

- `value.range` is one of the offered presets or `CUSTOM_RANGE` for manual selection. Presets default to `quickRanges` (15 presets, "Last 5 minutes" → "Last 1 year"); pass `ranges` to offer your own `DateTimeRange[]` (any `CUSTOM_RANGE` entry is filtered out of the list). `ranges={[]}` hides the quick-ranges column entirely — for hosts that render their own preset list.
- A `DateTimeRange` computes its start from "now" via `rangeSetter`; the end defaults to "now" unless `endSetter` is given (needed for closed periods like "Last month"). `name` is any string.
- Changes are staged until `onApply` fires — don't treat intermediate calendar clicks as committed.
- Dual-calendar layout appears at the `lg` breakpoint unless `compact` forces a single calendar.
- `minDate`/`maxDate` are day-granular; time inputs are independent of those bounds.
- `weekStartsOn` affects the calendar grid only, not quick-range math.
- Embedding in a host surface (e.g. inside a popover with the host's own sections): `showHeader={false}` drops the caps header band, `showTime={false}` switches to day-granular mode (no time segments, no "Now", date-only footer readout) — pair with a `className` that strips the card chrome (`shadow-none ring-0`).

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

A composable stat tile: a headline number, a `Badge` change pill, and an optional `Sparkline`. `Metric` is **content, not a surface** — wrap it in `<Card flush>` for the border. It's the one component here that depends on `@posthog/quill-charts` (for `Sparkline` + the headless metric math), which pulls d3 — so it lives behind its own `@posthog/quill-components/metric` entry point, **not** the main barrel. That keeps charts/d3 out of the always-eager app-shell graph: only code that imports the metric subpath pays for it.

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
- `labels` doubles as the sparkline's x-scale keys, so entries must be **unique** — a duplicate collapses two points onto one position and draws the series backwards (see the charts guide's `labels` rule). Pass raw keys (ISO dates) and render them for display with `formatLabel`, instead of pre-formatting text like `'June 16'`, which repeats once a range spans a year. `formatLabel` covers the subtitle; a `sparklineTooltip` formats the same keys through the charts' own `labelFormatter`.
- `MetricDelta` renders a `Badge`; `goodDirection` (default `up`) decides success vs destructive. It carries its own `TooltipProvider`, so `changeTooltip` needs no app-root setup. resize via `className` (the metric insight passes its own larger-pill classes and puts it inline next to the headline via `MetricHeader`; there is no `changeInline` or size prop, compose and style at the call site).
- Color the headline with `valueColor`, a function of the shown value, so a hovered point gets its own color (a threshold status). For a fixed color use a `text-*` class on `MetricValue`. The root `color` tints only the sparkline.
- Supports `restingSubtitle`, `hoverChangeFromPreviousPoint`, `changeTooltip`, and `positiveColor`/`negativeColor` for user-configured pill colors; omit the color props to keep the semantic `Badge` variants.
- `series` draws a multi-series sparkline (one line per series, the charts' `Series[]` shape) instead of the single `data` line. It's purely visual — the headline, hover and change pill still read `data`, so pass the numbers the tile should read (e.g. the per-index totals) as `data` alongside it; the types reject `series` without `data`. The single-line conveniences (`color`, `sparklineDashedFromIndex`) don't apply — set them per series.
- `sparklineTooltip` is a render prop passed straight to the sparkline (off by default, since hover already scrubs the headline) — supply `(ctx) => <DefaultTooltip {...ctx} />` to also show a hover tooltip, e.g. the per-series breakdown behind a multi-series total.
- Things `Metric` deliberately doesn't have props for — compose them yourself around it: a clickable tile (put the handler on the wrapping `Card`), a footer (a sibling node after `MetricSparkline`), an info icon next to the title (a `Tooltip` inside `MetricTitle`), and a loading state (render `Skeleton`s instead of the `Metric`).

## Maintenance

When adding or changing a component here, update this guide in the same PR and add a story next to the component.

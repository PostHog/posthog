// Types of `Tooltip`. Shared types it uses, declared in core.d.ts: TooltipContext, Series, SeriesType.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': DefaultTooltip, TooltipSurface, TooltipSwatch, TooltipFooter, DefaultTooltipProps.
// Other declarations here are shapes to match, not names to import.

export declare function DefaultTooltip<Meta = unknown>({
    label,
    seriesData,
    hoverPosition,
    hoveredSeriesKey,
    valueFormatter,
    labelFormatter,
    labelRenderer,
    showHeader,
    showTotal,
    totalLabel,
    totalFormatter,
    sortedByValue,
    hideZeroRows,
    onRowClick,
    footer,
}: DefaultTooltipProps<Meta>): React.ReactElement

export declare function TooltipSurface({
    children,
    className,
    'data-attr': dataAttr,
}: TooltipSurfaceProps): React.ReactElement

/** Round series-color swatch used in tooltip rows. */
export declare function TooltipSwatch({ color }: { color: string }): React.ReactElement

/** Divider plus muted row below a tooltip's content — e.g. a "click to inspect" hint. */
export declare function TooltipFooter({ children }: { children: React.ReactNode }): React.ReactElement

export interface DefaultTooltipProps<Meta = unknown> extends TooltipContext<Meta> {
    /** Formats each row's value. Receives the row's `seriesData` entry as a second argument so
     *  callers can format per-series — e.g. each SQL column with its own currency/duration/percent
     *  settings — rather than with one global formatter. Defaults to `toLocaleString`. Existing
     *  callers that take only `value` keep working (the extra argument is ignored). May return a
     *  node (e.g. a property-formatted value) and not just a string. */
    valueFormatter?: (value: number, entry: SeriesDatum<Meta>) => React.ReactNode
    /** Transforms the header label before display — use to convert raw ISO strings to human-
     *  readable dates. Defaults to rendering the label as-is. */
    labelFormatter?: (label: string) => React.ReactNode
    /** Overrides how each row's label renders. Defaults to the series label. Use for richer labels
     *  than a plain string — e.g. breakdown-value pills. */
    labelRenderer?: (entry: SeriesDatum<Meta>) => React.ReactNode
    /** Show the header label row. Defaults to true; pass false for charts without a meaningful
     *  header (e.g. pie slices, aggregated single-column bars). */
    showHeader?: boolean
    /** Append a footer row summing the visible series at the hovered point. `overlay` series
     *  (e.g. goal lines) and series with `visibility.total: false` (values that don't sum
     *  meaningfully, e.g. a percentage alongside counts) are excluded from the sum, and the row is
     *  suppressed when fewer than two summable series remain — a single-series total would just
     *  restate the one row. */
    showTotal?: boolean
    /** Label for the total row. Defaults to 'Total'. */
    totalLabel?: string
    /** Formats the total value. Defaults to the `valueFormatter` (applied with the first summable
     *  row's entry) or `toLocaleString`. */
    totalFormatter?: (value: number) => React.ReactNode
    /** Sort series rows by value descending so the highest value appears at the top. */
    sortedByValue?: boolean
    /** Hide rows whose value is exactly 0 — useful when a zero means the series is absent rather than measured. */
    hideZeroRows?: boolean
    /** Make each series row clickable, firing with the row's `seriesData` entry. The tooltip must
     *  be pinned for clicks to land (an unpinned tooltip has `pointer-events: none`). Used to open a
     *  drill-down (e.g. the persons modal) for a specific series. */
    onRowClick?: (entry: SeriesDatum<Meta>) => void
    /** Extra content rendered below all rows and the total, separated by a divider. */
    footer?: React.ReactNode
}

interface TooltipSurfaceProps {
    children: React.ReactNode
    className?: string
    /** Forwarded onto the panel — used for test/automation selectors. */
    'data-attr'?: string
}

type SeriesDatum<Meta> = TooltipContext<Meta>['seriesData'][number]

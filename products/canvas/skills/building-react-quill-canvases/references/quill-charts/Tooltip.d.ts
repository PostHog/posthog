// Types of `Tooltip`. Shared types it uses, declared in core.d.ts: DefaultTooltipProps, TooltipContext, SeriesDatum, Series, SeriesType.
// Generated from @posthog/quill-charts 0.3.0-beta.33, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': DefaultTooltip, TooltipSurface, TooltipSwatch, TooltipFooter.
// Other declarations here are shapes to match, not names to import.

export declare function DefaultTooltip<Meta = unknown>({
    label,
    seriesData,
    hoverPosition,
    hoveredSeriesKey,
    isPinned,
    valueFormatter,
    labelFormatter,
    labelRenderer,
    showHeader,
    showTotal,
    totalLabel,
    totalFormatter,
    sortedByValue,
    mode,
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

interface TooltipSurfaceProps {
    children: React.ReactNode
    className?: string
    /** Forwarded onto the panel — used for test/automation selectors. */
    'data-attr'?: string
}

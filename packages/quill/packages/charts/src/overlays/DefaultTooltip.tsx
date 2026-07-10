import { useCallback, useEffect, useRef, useState } from 'react'

import type { TooltipContext } from '../core/types'
import { TooltipSurface, TooltipSwatch } from './TooltipSurface'
import { findClosestSeriesKey } from './tooltipUtils'

type SeriesDatum<Meta> = TooltipContext<Meta>['seriesData'][number]

// Cap the scroll area to roughly 10 rows before scrolling kicks in.
const ROWS_MAX_HEIGHT = '14rem'

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
     *  (e.g. goal lines) are excluded from the sum, and the row is suppressed when fewer than two
     *  summable series remain — a single-series total would just restate the one row. */
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

export function DefaultTooltip<Meta = unknown>({
    label,
    seriesData,
    hoverPosition,
    valueFormatter,
    labelFormatter,
    labelRenderer,
    showHeader = true,
    showTotal,
    totalLabel = 'Total',
    totalFormatter,
    sortedByValue,
    hideZeroRows,
    onRowClick,
    footer,
}: DefaultTooltipProps<Meta>): React.ReactElement {
    const format = valueFormatter ?? ((value: number): React.ReactNode => value.toLocaleString())
    const visible = hideZeroRows ? seriesData.filter((s) => s.value !== 0) : seriesData
    const rows = sortedByValue
        ? [...visible].sort((a, b) => b.value - a.value)
        : visible[0]?.yPixel != null
          ? [...visible].sort((a, b) => (a.yPixel ?? Infinity) - (b.yPixel ?? Infinity))
          : visible
    const summable = rows.filter((s) => !s.series.overlay)
    const closestKey =
        hoverPosition != null && rows.length > 1 ? findClosestSeriesKey(rows, hoverPosition.y) : null
    const renderTotal = showTotal && summable.length > 1
    const total = summable.reduce((acc, s) => acc + s.value, 0)
    const formatTotal = totalFormatter ?? ((value: number): React.ReactNode => format(value, summable[0]))
    const scrollContainerRef = useRef<HTMLDivElement>(null)
    const [canScrollUp, setCanScrollUp] = useState(false)
    const [canScrollDown, setCanScrollDown] = useState(false)

    const updateScrollFades = useCallback(() => {
        const el = scrollContainerRef.current
        if (!el) {
            return
        }
        setCanScrollUp(el.scrollTop > 0)
        setCanScrollDown(el.scrollTop + el.clientHeight < el.scrollHeight - 1)
    }, [])

    useEffect(() => {
        updateScrollFades()
    }, [rows, updateScrollFades])

    useEffect(() => {
        if (!closestKey || !scrollContainerRef.current) {
            return
        }
        const container = scrollContainerRef.current
        const el = container.querySelector('[data-closest="true"]') as HTMLElement | null
        if (!el) {
            return
        }
        // Use getBoundingClientRect so the position is relative to the container's visible area,
        // not to the nearest positioned ancestor (which may not be the scroll container).
        const containerRect = container.getBoundingClientRect()
        const elRect = el.getBoundingClientRect()
        const elTopInView = elRect.top - containerRect.top
        const elBottomInView = elRect.bottom - containerRect.top
        // Scroll before the row enters the mask fade zone (top/bottom 20%), not just when it's
        // fully off-screen — otherwise the highlighted row can sit in the faded region.
        const fadeZone = container.clientHeight * 0.2
        if (elBottomInView > container.clientHeight - fadeZone) {
            container.scrollTop += elBottomInView - (container.clientHeight - fadeZone)
        } else if (elTopInView < fadeZone) {
            container.scrollTop += elTopInView - fadeZone
        }
    }, [closestKey])

    const maskImage = (() => {
        if (canScrollUp && canScrollDown) {
            return 'linear-gradient(to bottom, transparent, black 20%, black 80%, transparent)'
        }
        if (canScrollUp) {
            return 'linear-gradient(to bottom, transparent, black 20%)'
        }
        if (canScrollDown) {
            return 'linear-gradient(to bottom, black 80%, transparent)'
        }
        return undefined
    })()

    return (
        <TooltipSurface>
            {showHeader && (
                <div data-attr="hog-chart-tooltip-label" className="font-semibold mb-1 opacity-60">
                    {labelFormatter ? labelFormatter(label) : label}
                </div>
            )}
            <div
                ref={scrollContainerRef}
                onScroll={updateScrollFades}
                style={{
                    maxHeight: ROWS_MAX_HEIGHT,
                    overflowY: 'auto',
                    scrollbarWidth: 'none',
                    scrollBehavior: 'smooth',
                    maskImage,
                    WebkitMaskImage: maskImage,
                }}
            >
                {rows.map((s) => {
                    const isClosest = s.series.key === closestKey
                    const clickable = onRowClick ? ' cursor-pointer hover:bg-current/10' : ''
                    const labelContent = labelRenderer ? labelRenderer(s) : s.series.label
                    return (
                        <div
                            key={s.series.key}
                            data-attr="hog-chart-tooltip-row"
                            data-closest={isClosest ? 'true' : undefined}
                            className={`flex items-center gap-2 min-w-0 py-0.5 px-1.5 rounded transition-colors duration-150${isClosest ? ' font-semibold bg-current/[.1]' : ''}${clickable}`}
                            onClick={onRowClick ? () => onRowClick(s) : undefined}
                        >
                            <TooltipSwatch color={s.color} />
                            {/* Grid-stack the label so an invisible semibold ghost always reserves
                                the bold width — the visible span toggles weight without reflowing. */}
                            <span className="flex-1 min-w-0 overflow-hidden grid">
                                <span className="font-semibold invisible truncate [grid-area:1/1]" aria-hidden="true">
                                    {labelContent}
                                </span>
                                <span data-attr="hog-chart-tooltip-series" className="truncate [grid-area:1/1]">
                                    {labelContent}
                                </span>
                            </span>
                            <strong data-attr="hog-chart-tooltip-value" className="tabular-nums">
                                {format(s.value, s)}
                            </strong>
                        </div>
                    )
                })}
            </div>
            {renderTotal && (
                <div
                    data-attr="hog-chart-tooltip-total"
                    className="flex items-center gap-2 mt-2 pt-1 border-t border-current/25"
                >
                    <span className="flex-1 opacity-60">{totalLabel}</span>
                    <strong data-attr="hog-chart-tooltip-value">{formatTotal(total)}</strong>
                </div>
            )}
            {footer && (
                <div className="mt-1 pt-1 border-t border-current/25 text-xs opacity-60 text-center">{footer}</div>
            )}
        </TooltipSurface>
    )
}

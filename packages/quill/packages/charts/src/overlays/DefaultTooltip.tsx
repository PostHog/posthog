import { useEffect, useRef } from 'react'

import type { TooltipContext } from '../core/types'
import { TooltipSurface, TooltipSwatch } from './TooltipSurface'

type SeriesDatum<Meta> = TooltipContext<Meta>['seriesData'][number]

export interface DefaultTooltipProps<Meta = unknown> extends TooltipContext<Meta> {
    /** Formats each row's value. Receives the row's `seriesData` entry as a second argument so
     *  callers can format per-series — e.g. each SQL column with its own currency/duration/percent
     *  settings — rather than with one global formatter. Defaults to `toLocaleString`. Existing
     *  callers that take only `value` keep working (the extra argument is ignored). */
    valueFormatter?: (value: number, entry: SeriesDatum<Meta>) => string
    /** Transforms the header label before display — use to convert raw ISO strings to human-
     *  readable dates. Defaults to rendering the label as-is. */
    labelFormatter?: (label: string) => string
    /** Append a footer row summing the visible series at the hovered point. `overlay` series
     *  (e.g. goal lines) are excluded from the sum, and the row is suppressed when fewer than two
     *  summable series remain — a single-series total would just restate the one row. */
    showTotal?: boolean
    /** Label for the total row. Defaults to 'Total'. */
    totalLabel?: string
    /** Formats the total value. Defaults to the `valueFormatter` (applied with the first summable
     *  row's entry) or `toLocaleString`. */
    totalFormatter?: (value: number) => string
    /** Sort series rows by value descending so the highest value appears at the top. */
    sortedByValue?: boolean
    /** Cap the number of rows shown. When the sorted list is longer, a note shows how many
     *  are hidden. Defaults to showing all. */
    maxRows?: number
    /** Extra content rendered below all rows and the total, separated by a divider. */
    footer?: React.ReactNode
}

export function DefaultTooltip<Meta = unknown>({
    label,
    seriesData,
    hoverPosition,
    valueFormatter,
    labelFormatter,
    showTotal,
    totalLabel = 'Total',
    totalFormatter,
    sortedByValue,
    maxRows,
    footer,
}: DefaultTooltipProps<Meta>): React.ReactElement {
    const format = valueFormatter ?? ((value: number): string => value.toLocaleString())
    const rows = sortedByValue ? [...seriesData].sort((a, b) => b.value - a.value) : seriesData
    const summable = rows.filter((s) => !s.series.overlay)

    const closestKey =
        hoverPosition != null && rows.some((s) => s.yPixel != null)
            ? rows.reduce<{ key: string; dist: number } | null>((best, s) => {
                  if (s.yPixel == null) {
                      return best
                  }
                  const dist = Math.abs(s.yPixel - hoverPosition.y)
                  return best == null || dist < best.dist ? { key: s.series.key, dist } : best
              }, null)?.key
            : null
    const renderTotal = showTotal && summable.length > 1
    const total = summable.reduce((acc, s) => acc + s.value, 0)
    const formatTotal = totalFormatter ?? ((value: number): string => format(value, summable[0]))
    const scrollable = maxRows != null && rows.length > maxRows
    const scrollContainerRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (!scrollable || !closestKey || !scrollContainerRef.current) {
            return
        }
        const el = scrollContainerRef.current.querySelector('[data-closest="true"]')
        if (el) {
            el.scrollIntoView({ block: 'nearest' })
        }
    }, [closestKey, scrollable])

    return (
        <TooltipSurface>
            <div data-attr="hog-chart-tooltip-label" className="font-semibold mb-1 opacity-60">
                {labelFormatter ? labelFormatter(label) : label}
            </div>
            <div
                ref={scrollContainerRef}
                style={
                    scrollable
                        ? { maxHeight: `${maxRows! * 1.5}rem`, overflowY: 'auto', scrollbarWidth: 'none' }
                        : undefined
                }
            >
                {rows.map((s) => {
                    const isClosest = s.series.key === closestKey
                    return (
                        <div
                            key={s.series.key}
                            data-attr="hog-chart-tooltip-row"
                            data-closest={isClosest ? 'true' : undefined}
                            className={`flex items-center gap-2 min-w-0${isClosest ? ' font-semibold' : ''}`}
                        >
                            <TooltipSwatch color={s.color} />
                            <span data-attr="hog-chart-tooltip-series" className="flex-1 min-w-0 truncate">
                                {s.series.label}
                            </span>
                            <strong data-attr="hog-chart-tooltip-value">{format(s.value, s)}</strong>
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
            {footer && <div className="mt-1 pt-1 border-t border-current/25 text-xs opacity-60">{footer}</div>}
        </TooltipSurface>
    )
}

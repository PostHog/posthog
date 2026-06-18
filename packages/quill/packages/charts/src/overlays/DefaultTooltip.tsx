import type { TooltipContext } from '../core/types'
import { TooltipSurface, TooltipSwatch } from './TooltipSurface'

type SeriesDatum<Meta> = TooltipContext<Meta>['seriesData'][number]

interface DefaultTooltipProps<Meta = unknown> extends TooltipContext<Meta> {
    /** Formats each row's value. Receives the row's `seriesData` entry as a second argument so
     *  callers can format per-series — e.g. each SQL column with its own currency/duration/percent
     *  settings — rather than with one global formatter. Defaults to `toLocaleString`. Existing
     *  callers that take only `value` keep working (the extra argument is ignored). */
    valueFormatter?: (value: number, entry: SeriesDatum<Meta>) => string
    /** Append a footer row summing the visible series at the hovered point. `overlay` series
     *  (e.g. goal lines) are excluded from the sum, and the row is suppressed when fewer than two
     *  summable series remain — a single-series total would just restate the one row. */
    showTotal?: boolean
    /** Label for the total row. Defaults to 'Total'. */
    totalLabel?: string
    /** Formats the total value. Defaults to the `valueFormatter` (applied with the first summable
     *  row's entry) or `toLocaleString`. */
    totalFormatter?: (value: number) => string
}

export function DefaultTooltip<Meta = unknown>({
    label,
    seriesData,
    valueFormatter,
    showTotal,
    totalLabel = 'Total',
    totalFormatter,
}: DefaultTooltipProps<Meta>): React.ReactElement {
    const format = valueFormatter ?? ((value: number): string => value.toLocaleString())
    const summable = seriesData.filter((s) => !s.series.overlay)
    const renderTotal = showTotal && summable.length > 1
    const total = summable.reduce((acc, s) => acc + s.value, 0)
    const formatTotal = totalFormatter ?? ((value: number): string => format(value, summable[0]))

    return (
        <TooltipSurface>
            <div className="font-semibold mb-1">{label}</div>
            {seriesData.map((s) => (
                <div key={s.series.key} className="flex items-center gap-2">
                    <TooltipSwatch color={s.color} />
                    <span>{s.series.label}:</span>
                    <strong>{format(s.value, s)}</strong>
                </div>
            ))}
            {renderTotal && (
                <div className="flex items-center gap-2 mt-1 pt-1 border-t border-current/25 font-semibold">
                    <span className="w-2" />
                    <span>{totalLabel}:</span>
                    <strong>{formatTotal(total)}</strong>
                </div>
            )}
        </TooltipSurface>
    )
}

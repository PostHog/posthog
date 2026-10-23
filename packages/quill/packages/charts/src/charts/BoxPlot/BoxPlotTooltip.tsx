import React from 'react'

import type { TooltipContext } from '../../core/types'
import { TooltipSurface, TooltipSwatch } from '../../overlays/TooltipSurface'
import type { BoxPlotAdaptedMeta } from './BoxPlot'
import type { BoxPlotDatum } from './types'

interface TooltipRow {
    label: string
    value: number
}

/** Whisker rows only appear when a whisker is clipped, so it differs from the true bound. */
function tooltipRows(datum: BoxPlotDatum): TooltipRow[] {
    const { whiskerMin, whiskerMax } = datum
    const rows: (TooltipRow | null)[] = [
        { label: 'Max', value: datum.max },
        whiskerMax !== undefined && whiskerMax !== datum.max ? { label: 'Upper whisker', value: whiskerMax } : null,
        { label: '75th percentile', value: datum.p75 },
        { label: 'Median', value: datum.median },
        { label: 'Mean', value: datum.mean },
        { label: '25th percentile', value: datum.p25 },
        whiskerMin !== undefined && whiskerMin !== datum.min ? { label: 'Lower whisker', value: whiskerMin } : null,
        { label: 'Min', value: datum.min },
    ]
    return rows.filter((row): row is TooltipRow => row !== null)
}

export interface BoxPlotTooltipProps<Meta = unknown> {
    ctx: TooltipContext<BoxPlotAdaptedMeta<Meta>>
    /** Optional consumer override — passes the original TooltipContext through so the consumer
     *  can render their own template while still reading the original BoxPlotDatum from the
     *  adapter meta on each series. */
    userTooltip?: (ctx: TooltipContext<BoxPlotAdaptedMeta<Meta>>) => React.ReactNode
    /** Whether multiple series are being shown — drives whether each box's series label is
     *  printed in the header above its stats. */
    grouped: boolean
    /** Formats each statistic. Defaults to `toLocaleString`. */
    valueFormatter?: (value: number, entry: TooltipContext['seriesData'][number]) => string
}

function defaultFormatValue(v: number): string {
    return v.toLocaleString()
}

export function BoxPlotTooltip<Meta = unknown>({
    ctx,
    userTooltip,
    grouped,
    valueFormatter = defaultFormatValue,
}: BoxPlotTooltipProps<Meta>): React.ReactElement | null {
    if (userTooltip) {
        return <>{userTooltip(ctx)}</>
    }

    const entries: { datum: BoxPlotDatum; seriesEntry: TooltipContext['seriesData'][number] }[] = []
    for (const seriesEntry of ctx.seriesData) {
        if (seriesEntry.series.visibility?.tooltip === false) {
            continue
        }
        const datum = seriesEntry.series.meta?.datums?.[ctx.dataIndex]
        if (!datum) {
            continue
        }
        entries.push({ datum, seriesEntry })
    }
    if (entries.length === 0) {
        return null
    }

    return (
        <TooltipSurface data-attr="hog-chart-boxplot-tooltip">
            <div className="font-semibold mb-1">{ctx.label}</div>
            {entries.map((entry, i) => (
                <div key={entry.seriesEntry.series.key} className={i > 0 ? 'mt-2' : undefined}>
                    {grouped && (
                        <div className="flex items-center gap-2 mb-1">
                            <TooltipSwatch color={entry.seriesEntry.color} />
                            <span className="font-semibold">{entry.seriesEntry.series.label}</span>
                        </div>
                    )}
                    <table className="border-collapse">
                        <tbody>
                            {tooltipRows(entry.datum).map((row) => (
                                <tr key={row.label}>
                                    <td className="pr-3 opacity-70">{row.label}</td>
                                    <td className="font-medium">
                                        {Number.isFinite(row.value)
                                            ? valueFormatter(row.value, entry.seriesEntry)
                                            : '—'}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            ))}
        </TooltipSurface>
    )
}

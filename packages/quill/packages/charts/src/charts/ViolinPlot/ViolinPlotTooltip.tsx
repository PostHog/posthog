import React from 'react'

import type { TooltipContext } from '../../core/types'
import { TooltipSurface, TooltipSwatch } from '../../overlays/TooltipSurface'
import { summarizeViolin } from './computeViolinLayout'
import type { ViolinSummary } from './types'
import type { ViolinPlotAdaptedMeta } from './ViolinPlot'

interface TooltipRow {
    label: string
    value: number
    isCount?: boolean
}

function tooltipRows(summary: ViolinSummary): TooltipRow[] {
    return [
        { label: 'Count', value: summary.count, isCount: true },
        { label: 'Max', value: summary.max },
        { label: '75th percentile', value: summary.p75 },
        { label: 'Median', value: summary.median },
        { label: 'Mean', value: summary.mean },
        { label: '25th percentile', value: summary.p25 },
        { label: 'Min', value: summary.min },
    ]
}

export interface ViolinPlotTooltipProps<Meta = unknown> {
    ctx: TooltipContext<ViolinPlotAdaptedMeta<Meta>>
    /** Optional consumer override — receives the original TooltipContext so the consumer can render
     *  their own template while still reading the `ViolinPlotDatum` from the adapter meta. */
    userTooltip?: (ctx: TooltipContext<ViolinPlotAdaptedMeta<Meta>>) => React.ReactNode
    /** The value axis is logarithmic: values that are not positive are left out of the statistics,
     *  as they are left out of the drawing. */
    logScale?: boolean
    /** Whether multiple series are being shown — drives whether each violin's series label is
     *  printed in the header above its stats. */
    grouped: boolean
    /** Formats each statistic. Defaults to `toLocaleString`. */
    valueFormatter?: (value: number, entry: TooltipContext['seriesData'][number]) => string
}

function defaultFormatValue(value: number): string {
    return value.toLocaleString()
}

export function ViolinPlotTooltip<Meta = unknown>({
    ctx,
    userTooltip,
    logScale = false,
    grouped,
    valueFormatter = defaultFormatValue,
}: ViolinPlotTooltipProps<Meta>): React.ReactElement | null {
    if (userTooltip) {
        return <>{userTooltip(ctx)}</>
    }

    const entries: { summary: ViolinSummary; seriesEntry: TooltipContext['seriesData'][number] }[] = []
    for (const seriesEntry of ctx.seriesData) {
        if (seriesEntry.series.visibility?.tooltip === false) {
            continue
        }
        const datum = seriesEntry.series.meta?.datums?.[ctx.dataIndex]
        const summary = datum ? summarizeViolin(datum, logScale) : null
        if (summary) {
            entries.push({ summary, seriesEntry })
        }
    }
    if (entries.length === 0) {
        return null
    }

    return (
        <TooltipSurface data-attr="hog-chart-violinplot-tooltip">
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
                            {tooltipRows(entry.summary).map((row) => (
                                <tr key={row.label}>
                                    <td className="pr-3 opacity-70">{row.label}</td>
                                    <td className="font-medium">
                                        {Number.isFinite(row.value)
                                            ? row.isCount
                                                ? row.value.toLocaleString()
                                                : valueFormatter(row.value, entry.seriesEntry)
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

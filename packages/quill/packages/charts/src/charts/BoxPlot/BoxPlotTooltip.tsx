import React from 'react'

import { useChartLayout } from '../../core/chart-context'
import type { TooltipContext } from '../../core/types'
import type { BoxPlotAdaptedMeta } from './BoxPlot'
import type { BoxPlotDatum } from './computeBoxLayout'

const DEFAULT_TOOLTIP_BG = '#1d2330'
const DEFAULT_TOOLTIP_COLOR = '#ffffff'

/** Rows shown per box, in the same order the legacy BoxPlotChart used. */
const ROWS: { label: string; key: keyof BoxPlotDatum }[] = [
    { label: 'Max', key: 'max' },
    { label: '75th percentile', key: 'p75' },
    { label: 'Median', key: 'median' },
    { label: 'Mean', key: 'mean' },
    { label: '25th percentile', key: 'p25' },
    { label: 'Min', key: 'min' },
]

export interface BoxPlotTooltipProps<Meta = unknown> {
    ctx: TooltipContext<BoxPlotAdaptedMeta<Meta>>
    /** Optional consumer override — passes the original TooltipContext through so the consumer
     *  can render their own template while still reading the original BoxPlotDatum from the
     *  adapter meta on each series. */
    userTooltip?: (ctx: TooltipContext<BoxPlotAdaptedMeta<Meta>>) => React.ReactNode
    /** Whether multiple series are being shown — drives whether each box's series label is
     *  printed in the header above its stats. */
    grouped: boolean
}

function defaultFormatValue(v: number): string {
    return Number.isFinite(v) ? v.toLocaleString() : '—'
}

export function BoxPlotTooltip<Meta = unknown>({
    ctx,
    userTooltip,
    grouped,
}: BoxPlotTooltipProps<Meta>): React.ReactElement | null {
    const { theme } = useChartLayout()

    if (userTooltip) {
        return <>{userTooltip(ctx)}</>
    }

    const entries: { key: string; color: string; label: string; datum: BoxPlotDatum }[] = []
    for (const seriesEntry of ctx.seriesData) {
        if (seriesEntry.series.visibility?.tooltip === false) {
            continue
        }
        const datum = seriesEntry.series.meta?.datums?.[ctx.dataIndex]
        if (!datum) {
            continue
        }
        entries.push({
            key: seriesEntry.series.key,
            color: seriesEntry.color,
            label: seriesEntry.series.label,
            datum,
        })
    }
    if (entries.length === 0) {
        return null
    }

    return (
        <div
            className="px-3 py-2 rounded-lg shadow-lg text-[13px]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                backgroundColor: theme.tooltipBackground ?? DEFAULT_TOOLTIP_BG,
                color: theme.tooltipColor ?? DEFAULT_TOOLTIP_COLOR,
            }}
            data-attr="hog-chart-boxplot-tooltip"
        >
            <div className="font-semibold mb-1">{ctx.label}</div>
            {entries.map((entry, i) => (
                <div key={entry.key} className={i > 0 ? 'mt-2' : undefined}>
                    {grouped && (
                        <div className="flex items-center gap-2 mb-1">
                            <span
                                className="inline-block size-2 rounded-full"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ backgroundColor: entry.color }}
                            />
                            <span className="font-semibold">{entry.label}</span>
                        </div>
                    )}
                    <table className="border-collapse">
                        <tbody>
                            {ROWS.map((row) => (
                                <tr key={row.key}>
                                    <td className="pr-3 opacity-70">{row.label}</td>
                                    <td className="font-medium">
                                        {defaultFormatValue(entry.datum[row.key] as number)}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            ))}
        </div>
    )
}

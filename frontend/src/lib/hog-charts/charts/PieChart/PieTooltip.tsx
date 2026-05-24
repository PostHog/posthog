import React from 'react'

import { useChartLayout } from '../../core/chart-context'
import type { TooltipContext } from '../../core/types'

export interface PieTooltipProps<Meta> {
    ctx: TooltipContext<Meta>
    valueFormatter?: (value: number) => string
    isPercent?: boolean
}

const DEFAULT_TOOLTIP_BG = '#1d2330'
const DEFAULT_TOOLTIP_COLOR = '#ffffff'

function defaultFormatter(v: number): string {
    return v.toLocaleString()
}

function formatPercent(fraction: number): string {
    return `${Math.round(fraction * 1000) / 10}%`
}

export function PieTooltip<Meta>({
    ctx,
    valueFormatter = defaultFormatter,
    isPercent = false,
}: PieTooltipProps<Meta>): React.ReactElement | null {
    const { theme } = useChartLayout()
    const entry = ctx.seriesData[0]
    if (!entry) {
        return null
    }
    const share = entry.fraction ?? 0

    return (
        <div
            className="px-3 py-2 rounded-lg shadow-lg text-[13px]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                backgroundColor: theme.tooltipBackground ?? DEFAULT_TOOLTIP_BG,
                color: theme.tooltipColor ?? DEFAULT_TOOLTIP_COLOR,
            }}
        >
            <div className="flex items-center gap-2 mb-1">
                <span
                    className="inline-block size-2 rounded-full"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ backgroundColor: entry.color }}
                />
                <span className="font-semibold">{entry.series.label}</span>
            </div>
            <div className="flex items-center gap-2">
                <strong>{isPercent ? formatPercent(share) : valueFormatter(entry.value)}</strong>
                {!isPercent && share > 0 ? <span className="opacity-70">({formatPercent(share)})</span> : null}
            </div>
        </div>
    )
}

import React from 'react'

import type { TooltipContext } from '../../core/types'
import { TooltipSurface, TooltipSwatch } from '../../overlays/TooltipSurface'

export interface PieTooltipProps<Meta> {
    ctx: TooltipContext<Meta>
    valueFormatter?: (value: number) => string
    isPercent?: boolean
}

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
    const entry = ctx.seriesData[0]
    if (!entry) {
        return null
    }
    const share = entry.fraction ?? 0

    return (
        <TooltipSurface>
            <div className="flex items-center gap-2 mb-1">
                <TooltipSwatch color={entry.color} />
                <span className="font-semibold">{entry.series.label}</span>
            </div>
            <div className="flex items-center gap-2">
                <strong>{isPercent ? formatPercent(share) : valueFormatter(entry.value)}</strong>
                {!isPercent && share > 0 ? <span className="opacity-70">({formatPercent(share)})</span> : null}
            </div>
        </TooltipSurface>
    )
}

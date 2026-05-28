import React from 'react'

import type { BarChartPrivate } from '../../core/bar-layout'
import { useChartLayout } from '../../core/chart-context'
import type { BarScaleSet, StackedBand } from '../../core/scales'
import type { TooltipContext } from '../../core/types'
import { DefaultTooltip } from '../../overlays/DefaultTooltip'
import { seriesKeysAtCursor, strictSeriesKeyAtCursor } from './utils/bars-under-cursor'

export interface BarTooltipProps<Meta> {
    ctx: TooltipContext<Meta>
    userTooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    stackedData: Map<string, StackedBand> | undefined
    topStackedKeyByAxis: Map<string, string>
    layout: 'stacked' | 'grouped' | 'percent'
    isHorizontal: boolean
}

export function BarTooltip<Meta>({
    ctx,
    userTooltip,
    stackedData,
    topStackedKeyByAxis,
    layout,
    isHorizontal,
}: BarTooltipProps<Meta>): React.ReactElement | null {
    const { scales } = useChartLayout()
    const d3Scales = (scales._private as BarChartPrivate | undefined)?.__barChart
    if (d3Scales && ctx.hoverPosition && ctx.dataIndex >= 0) {
        const narrowed = narrowSeriesByCursor(ctx, d3Scales, layout, isHorizontal, stackedData, topStackedKeyByAxis)
        if (!narrowed) {
            return null
        }
        return <>{userTooltip ? userTooltip(narrowed) : DefaultTooltip(narrowed)}</>
    }
    return <>{userTooltip ? userTooltip(ctx) : DefaultTooltip(ctx)}</>
}

/** Returns null when no bar sits under the cursor on the band axis. For stacked/percent
 *  layouts the value-axis-resolved segment is bubbled to `seriesData[0]`. */
function narrowSeriesByCursor<Meta>(
    ctx: TooltipContext<Meta>,
    scales: BarScaleSet,
    layout: 'stacked' | 'grouped' | 'percent',
    isHorizontal: boolean,
    stackedData: Map<string, StackedBand> | undefined,
    topStackedKeyByAxis: Map<string, string>
): TooltipContext<Meta> | null {
    const cursor = ctx.hoverPosition
    if (!cursor) {
        return ctx
    }
    const seriesList = ctx.seriesData.map((entry) => entry.series)
    const cursorArgs = {
        series: seriesList,
        label: ctx.label,
        dataIndex: ctx.dataIndex,
        cursor,
        scales,
        layout,
        isHorizontal,
        stackedData,
        topStackedKeyByAxis,
    }
    const hits = seriesKeysAtCursor(cursorArgs)
    if (hits.size === 0) {
        return null
    }
    let filtered = ctx.seriesData.filter((entry) => hits.has(entry.series.key))
    if ((layout === 'stacked' || layout === 'percent') && filtered.length > 1) {
        const strictHit = strictSeriesKeyAtCursor(cursorArgs)
        if (strictHit) {
            const idx = filtered.findIndex((entry) => entry.series.key === strictHit)
            if (idx > 0) {
                filtered = [filtered[idx], ...filtered.slice(0, idx), ...filtered.slice(idx + 1)]
            }
        }
    }
    return { ...ctx, seriesData: filtered }
}

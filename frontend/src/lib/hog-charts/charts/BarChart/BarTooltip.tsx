import React from 'react'

import type { BarChartPrivate } from '../../core/bar-layout'
import { useChartLayout } from '../../core/chart-context'
import type { BarScaleSet, StackedBand } from '../../core/scales'
import type { TooltipContext } from '../../core/types'
import { DefaultTooltip } from '../../overlays/DefaultTooltip'
import { seriesKeysAtCursor } from './utils/bars-under-cursor'

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
}: BarTooltipProps<Meta>): React.ReactElement {
    const { scales } = useChartLayout()
    const d3Scales = (scales._private as BarChartPrivate | undefined)?.__barChart
    const narrowed =
        layout === 'grouped' && d3Scales && ctx.hoverPosition && ctx.dataIndex >= 0
            ? narrowSeriesByCursor(ctx, d3Scales, layout, isHorizontal, stackedData, topStackedKeyByAxis)
            : ctx
    return <>{userTooltip ? userTooltip(narrowed) : DefaultTooltip(narrowed)}</>
}

function narrowSeriesByCursor<Meta>(
    ctx: TooltipContext<Meta>,
    scales: BarScaleSet,
    layout: 'stacked' | 'grouped' | 'percent',
    isHorizontal: boolean,
    stackedData: Map<string, StackedBand> | undefined,
    topStackedKeyByAxis: Map<string, string>
): TooltipContext<Meta> {
    const cursor = ctx.hoverPosition
    if (!cursor) {
        return ctx
    }
    const hits = seriesKeysAtCursor({
        series: ctx.seriesData.map((entry) => entry.series),
        label: ctx.label,
        dataIndex: ctx.dataIndex,
        cursor,
        scales,
        layout,
        isHorizontal,
        stackedData,
        topStackedKeyByAxis,
    })
    if (hits.size === 0) {
        return ctx
    }
    return { ...ctx, seriesData: ctx.seriesData.filter((entry) => hits.has(entry.series.key)) }
}

import React from 'react'

import type { BarChartPrivate } from '../../core/bar-layout'
import { useChartLayout } from '../../core/chart-context'
import type { BarScaleSet, StackedBand } from '../../core/scales'
import type { TooltipContext } from '../../core/types'
import { DefaultTooltip } from '../../overlays/DefaultTooltip'
import {
    type BarLayout,
    findVisibleStackedSegment,
    isStackedLayout,
    resolveBarsAtCursor,
} from './utils/bars-under-cursor'

export interface BarTooltipProps<Meta> {
    ctx: TooltipContext<Meta>
    userTooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    stackedData: Map<string, StackedBand> | undefined
    topStackedKeyByAxis: Map<string, string>
    layout: BarLayout
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
    const { scales, labels } = useChartLayout()
    const d3Scales = (scales._private as BarChartPrivate | undefined)?.__barChart
    if (d3Scales && ctx.hoverPosition && ctx.dataIndex >= 0) {
        const narrowed = narrowSeriesByCursor(
            ctx,
            d3Scales,
            layout,
            isHorizontal,
            stackedData,
            topStackedKeyByAxis,
            labels
        )
        if (!narrowed) {
            return null
        }
        return <>{userTooltip ? userTooltip(narrowed) : DefaultTooltip(narrowed)}</>
    }
    return <>{userTooltip ? userTooltip(ctx) : DefaultTooltip(ctx)}</>
}

/** Moves the cursor-resolved segment to seriesData[0] and (for sparse-stacked overlap)
 *  re-reads its value at its own dataIndex so it isn't a zero from a band-collapsed cell. */
function narrowSeriesByCursor<Meta>(
    ctx: TooltipContext<Meta>,
    scales: BarScaleSet,
    layout: BarLayout,
    isHorizontal: boolean,
    stackedData: Map<string, StackedBand> | undefined,
    topStackedKeyByAxis: Map<string, string>,
    labels: string[]
): TooltipContext<Meta> | null {
    const cursor = ctx.hoverPosition
    if (!cursor) {
        return ctx
    }
    const seriesList = ctx.seriesData.map((entry) => entry.series)
    const { hits } = resolveBarsAtCursor({
        series: seriesList,
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
        return null
    }
    let visibleKey: string | null = null
    let visibleDataIndex: number | null = null
    if (isStackedLayout(layout)) {
        const visible = findVisibleStackedSegment({
            series: seriesList,
            labels,
            hoveredLabel: ctx.label,
            cursor,
            scales,
            layout,
            isHorizontal,
            stackedData,
            topStackedKeyByAxis,
        })
        if (visible) {
            visibleKey = visible.series.key
            visibleDataIndex = visible.dataIndex
        }
    }
    let filtered = ctx.seriesData.filter((entry) => hits.has(entry.series.key))
    if (isStackedLayout(layout) && filtered.length > 1 && visibleKey) {
        const idx = filtered.findIndex((entry) => entry.series.key === visibleKey)
        if (idx > 0) {
            filtered = [filtered[idx], ...filtered.filter((_, i) => i !== idx)]
        }
    }
    // `entry.value` was resolved at ctx.dataIndex, which for sparse-stacked overlap is a
    // zero cell for the visible series. Re-read from its own dataIndex.
    if (visibleKey != null && visibleDataIndex != null && visibleDataIndex !== ctx.dataIndex) {
        filtered = filtered.map((entry) => {
            if (entry.series.key !== visibleKey) {
                return entry
            }
            const raw = entry.series.data[visibleDataIndex!]
            const value = typeof raw === 'number' && Number.isFinite(raw) ? raw : entry.value
            return { ...entry, value }
        })
    }
    return { ...ctx, seriesData: filtered }
}

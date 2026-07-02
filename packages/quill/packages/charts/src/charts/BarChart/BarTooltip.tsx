import React from 'react'

import type { BarChartPrivate } from '../../core/bar-layout'
import { useChartLayout } from '../../core/chart-context'
import type { BarScaleSet, StackedBand } from '../../core/scales'
import type { Series, TooltipConfig, TooltipContext } from '../../core/types'
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
    /** Every drawn series, including those hidden from the tooltip — the visible-segment
     *  hit-test must see the full stack, not just the tooltip-visible subset. */
    allSeries: Series<Meta>[]
    stackedData: Map<string, StackedBand> | undefined
    topStackedKeyByAxis: Map<string, string>
    layout: BarLayout
    isHorizontal: boolean
    tooltipConfig?: TooltipConfig
}

export function BarTooltip<Meta>({
    ctx,
    userTooltip,
    allSeries,
    stackedData,
    topStackedKeyByAxis,
    layout,
    isHorizontal,
    tooltipConfig,
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
            labels,
            allSeries
        )
        if (!narrowed) {
            return null
        }
        return <>{userTooltip ? userTooltip(narrowed) : <DefaultTooltip {...narrowed} {...tooltipConfig} />}</>
    }
    return <>{userTooltip ? userTooltip(ctx) : <DefaultTooltip {...ctx} {...tooltipConfig} />}</>
}

/** Filters seriesData to only the segments hit by the cursor, and (for sparse-stacked overlap)
 *  re-reads the visible segment's value at its own dataIndex so it isn't a zero from a band-collapsed cell. */
function narrowSeriesByCursor<Meta>(
    ctx: TooltipContext<Meta>,
    scales: BarScaleSet,
    layout: BarLayout,
    isHorizontal: boolean,
    stackedData: Map<string, StackedBand> | undefined,
    topStackedKeyByAxis: Map<string, string>,
    labels: string[],
    allSeries: Series<Meta>[]
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
            series: allSeries,
            labels,
            hoveredLabel: ctx.label,
            cursor,
            scales,
            layout,
            isHorizontal,
            stackedData,
            topStackedKeyByAxis,
        })
        // No filled segment under the cursor — it's in the empty track past the bar's value
        // extent (e.g. right of the longest horizontal bar). Suppress rather than show a tooltip.
        if (!visible) {
            return null
        }
        visibleKey = visible.series.key
        visibleDataIndex = visible.dataIndex
    }
    // Surface the hovered identity so consumer tooltips can single out the segment/bar the
    // cursor is actually over — stacked keeps every segment in seriesData, so index 0 is not it.
    const hoveredSeriesKey = visibleKey ?? (hits.size === 1 ? hits.values().next().value : undefined)
    const filtered = ctx.seriesData.filter((entry) => hits.has(entry.series.key))
    // For sparse-stacked overlap ctx.dataIndex is a zero cell for the visible series. Rewrite
    // the entry's value (and ctx.dataIndex) to the segment's own index so row clicks route
    // correctly downstream.
    if (visibleKey != null && visibleDataIndex != null && visibleDataIndex !== ctx.dataIndex) {
        const di = visibleDataIndex
        const revalued = filtered.map((entry) => {
            if (entry.series.key !== visibleKey) {
                return entry
            }
            const raw = entry.series.data[di]
            const value = typeof raw === 'number' && Number.isFinite(raw) ? raw : entry.value
            return { ...entry, value }
        })
        return { ...ctx, seriesData: revalued, dataIndex: di, hoveredSeriesKey }
    }
    return { ...ctx, seriesData: filtered, hoveredSeriesKey }
}

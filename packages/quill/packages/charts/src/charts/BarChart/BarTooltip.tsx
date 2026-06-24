import React from 'react'

import type { BarChartPrivate } from '../../core/bar-layout'
import { useChartHover, useChartLayout } from '../../core/chart-context'
import type { BarScaleSet, StackedBand } from '../../core/scales'
import type { Series, TooltipContext } from '../../core/types'
import { DefaultTooltip } from '../../overlays/DefaultTooltip'
import {
    type BarLayout,
    findVisibleStackedSegment,
    isStackedLayout,
    resolveBarsAtCursor,
} from './utils/bars-under-cursor'

/** Affordance shown in the stacked-bar tooltip footer when the isolate modifier isn't held. */
export const SHIFT_ISOLATE_HINT = 'Hold ⇧ Shift to highlight a single series'

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
    /** Whether hold-Shift-to-isolate applies to this chart (stacked/percent, multi-series). When
     *  set, holding Shift narrows the tooltip to the segment under the cursor; otherwise a hint
     *  footer advertises the affordance. */
    isolateEnabled: boolean
}

export function BarTooltip<Meta>({
    ctx,
    userTooltip,
    allSeries,
    stackedData,
    topStackedKeyByAxis,
    layout,
    isHorizontal,
    isolateEnabled,
}: BarTooltipProps<Meta>): React.ReactElement | null {
    const { scales, labels } = useChartLayout()
    const { modifierActive } = useChartHover()
    const isolate = isolateEnabled && modifierActive
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
            allSeries,
            isolate
        )
        if (!narrowed) {
            return null
        }
        if (userTooltip) {
            return <>{userTooltip(narrowed)}</>
        }
        // Advertise the isolate affordance only when it would actually narrow something — a
        // multi-segment band, modifier not yet held.
        const showHint = isolateEnabled && !modifierActive && narrowed.seriesData.length > 1
        return <>{DefaultTooltip({ ...narrowed, footer: showHint ? SHIFT_ISOLATE_HINT : undefined })}</>
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
    labels: string[],
    allSeries: Series<Meta>[],
    /** When true (Shift held on a stacked layout), keep only the single segment under the cursor
     *  instead of the whole stack — matching the classic insight's "highlight individual bars". */
    isolate = false
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
    let filtered = ctx.seriesData.filter((entry) => hits.has(entry.series.key))
    // Shift held: collapse the stack to just the segment under the cursor.
    if (isolate && isStackedLayout(layout) && visibleKey) {
        filtered = filtered.filter((entry) => entry.series.key === visibleKey)
    }
    if (isStackedLayout(layout) && filtered.length > 1 && visibleKey) {
        const idx = filtered.findIndex((entry) => entry.series.key === visibleKey)
        if (idx > 0) {
            filtered = [filtered[idx], ...filtered.filter((_, i) => i !== idx)]
        }
    }
    // For sparse-stacked overlap ctx.dataIndex is a zero cell for the visible series. Rewrite
    // the entry's value (and ctx.dataIndex) to the segment's own index so row clicks route
    // correctly downstream.
    if (visibleKey != null && visibleDataIndex != null && visibleDataIndex !== ctx.dataIndex) {
        const di = visibleDataIndex
        filtered = filtered.map((entry) => {
            if (entry.series.key !== visibleKey) {
                return entry
            }
            const raw = entry.series.data[di]
            const value = typeof raw === 'number' && Number.isFinite(raw) ? raw : entry.value
            return { ...entry, value }
        })
        return { ...ctx, seriesData: filtered, dataIndex: di }
    }
    return { ...ctx, seriesData: filtered }
}

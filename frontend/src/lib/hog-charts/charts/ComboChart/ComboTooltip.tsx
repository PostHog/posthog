import React from 'react'

import { useChartLayout } from '../../core/chart-context'
import type { ComboChartPrivate } from '../../core/combo-scales'
import { resolveSeriesType } from '../../core/combo-scales'
import type { StackedBand } from '../../core/scales'
import type { SeriesType, TooltipContext } from '../../core/types'
import { DefaultTooltip } from '../../overlays/DefaultTooltip'
import { barKeysAtCursor } from './utils/combo-bar-hit'

export interface ComboTooltipProps<Meta> {
    ctx: TooltipContext<Meta>
    userTooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    barStackedData: Map<string, StackedBand> | undefined
    topStackedKeyByAxis: Map<string, string>
    layout: 'stacked' | 'grouped'
    defaultSeriesType: SeriesType
}

/** Narrows the tooltip's bar entries to the bar(s) the cursor is on. Lines/areas are always
 *  kept — they don't have a band-axis cursor extent, so the nearest-column hover index is
 *  enough to surface them. Returns null when the cursor is in a band gap and no line/area
 *  series exists either. */
export function ComboTooltip<Meta>({
    ctx,
    userTooltip,
    barStackedData,
    topStackedKeyByAxis,
    layout,
    defaultSeriesType,
}: ComboTooltipProps<Meta>): React.ReactElement | null {
    const { scales } = useChartLayout()
    const comboScales = (scales._private as ComboChartPrivate | undefined)?.__comboChart
    if (!comboScales || !ctx.hoverPosition || ctx.dataIndex < 0) {
        return <>{userTooltip ? userTooltip(ctx) : DefaultTooltip(ctx)}</>
    }
    const barHits = barKeysAtCursor({
        series: ctx.seriesData.map((entry) => entry.series),
        label: ctx.label,
        dataIndex: ctx.dataIndex,
        cursor: ctx.hoverPosition,
        scales: comboScales,
        layout,
        barStackedData,
        topStackedKeyByAxis,
        defaultSeriesType,
    })
    const filtered = ctx.seriesData.filter((entry) => {
        if (resolveSeriesType(entry.series, defaultSeriesType) === 'bar') {
            return barHits.has(entry.series.key)
        }
        return true
    })
    if (filtered.length === 0) {
        return null
    }
    const narrowed: TooltipContext<Meta> = { ...ctx, seriesData: filtered }
    return <>{userTooltip ? userTooltip(narrowed) : DefaultTooltip(narrowed)}</>
}

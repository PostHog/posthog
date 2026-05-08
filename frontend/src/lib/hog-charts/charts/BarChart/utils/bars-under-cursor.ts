import { computeBarAtIndex } from '../../../core/bar-layout'
import type { BarRect } from '../../../core/canvas-renderer'
import type { BarScaleSet, StackedBand } from '../../../core/scales'
import type { Series } from '../../../core/types'
import { DEFAULT_Y_AXIS_ID } from '../../../core/types'

export function barContainsPoint(bar: BarRect, point: { x: number; y: number }): boolean {
    return point.x >= bar.x && point.x <= bar.x + bar.width && point.y >= bar.y && point.y <= bar.y + bar.height
}

export interface SeriesKeysAtCursorArgs {
    series: readonly Pick<Series, 'key' | 'visibility' | 'yAxisId' | 'data'>[]
    label: string
    dataIndex: number
    cursor: { x: number; y: number }
    scales: BarScaleSet
    layout: 'stacked' | 'grouped' | 'percent'
    isHorizontal: boolean
    stackedData?: Map<string, StackedBand>
    topStackedKeyByAxis: Map<string, string>
}

/** Shared by drawHover and the tooltip wrapper so they can't drift. */
export function seriesKeysAtCursor(args: SeriesKeysAtCursorArgs): Set<string> {
    const { series, label, dataIndex, cursor, scales, layout, isHorizontal, stackedData, topStackedKeyByAxis } = args
    const hits = new Set<string>()
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        const stackedBand = stackedData?.get(s.key)
        const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
        const isTopOfStack = topStackedKeyByAxis.get(axisId) === s.key
        const bar = computeBarAtIndex({
            series: s as Series,
            label,
            dataIndex,
            scales,
            layout,
            isHorizontal,
            stackedBand,
            isTopOfStack,
        })
        if (bar && barContainsPoint(bar, cursor)) {
            hits.add(s.key)
        }
    }
    return hits
}

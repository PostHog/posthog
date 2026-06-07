import type { BarScaleSet, StackedBand } from '../../../core/scales'
import type { PointClickData, Series } from '../../../core/types'
import {
    type BarLayout,
    barContainsPointOnBandAxis,
    cursorOutsideBarFillExtent,
    findVisibleStackedSegment,
    iterBarsAtCursor,
} from './bars-under-cursor'

export interface ResolveClickedBarSeriesOptions<Meta> {
    clickData: PointClickData<Meta>
    d3Scales: BarScaleSet
    barLayout: BarLayout
    isHorizontal: boolean
    stackedData: Map<string, StackedBand> | undefined
    topStackedKeyByAxis: Map<string, string>
    series: Series<Meta>[]
    labels: readonly string[]
}

/** Rewrites the click payload to the bar series actually under the cursor. The base payload
 *  always points at the first series in the band; this picks the right one per layout:
 *   - grouped: the series whose sub-band column the cursor is over — band axis only, so a
 *     click above a short bar (or on its track) still resolves to that column.
 *   - stacked/percent: the segment whose rect contains the cursor on the value axis, walking
 *     every dataIndex in the band so sparse-overlap segments route correctly, and re-reading
 *     the value at that segment's own dataIndex.
 *  Pure so the routing is unit-testable; returns `null` to pass `clickData` through unchanged. */
export function resolveClickedBarSeries<Meta>({
    clickData,
    d3Scales,
    barLayout,
    isHorizontal,
    stackedData,
    topStackedKeyByAxis,
    series,
    labels,
}: ResolveClickedBarSeriesOptions<Meta>): PointClickData<Meta> | null {
    const { cursor, label, dataIndex, crossSeriesData } = clickData
    if (!cursor) {
        return null
    }
    const rewrite = (hitSeries: Series<Meta>, value: number, hitDataIndex: number): PointClickData<Meta> => ({
        ...clickData,
        dataIndex: hitDataIndex,
        series: hitSeries,
        value,
        seriesIndex: series.findIndex((s) => s.key === hitSeries.key),
    })

    if (barLayout === 'grouped') {
        for (const { series: s, bar } of iterBarsAtCursor({
            series: crossSeriesData.map((d) => d.series),
            label,
            dataIndex,
            scales: d3Scales,
            layout: barLayout,
            isHorizontal,
            topStackedKeyByAxis,
        })) {
            if (!barContainsPointOnBandAxis(bar, cursor, isHorizontal)) {
                continue
            }
            const hit = crossSeriesData.find((d) => d.series.key === s.key)
            if (!hit) {
                return null
            }
            const inTrackArea = cursorOutsideBarFillExtent(bar, cursor, isHorizontal)
            return { ...rewrite(hit.series, hit.value, dataIndex), inTrackArea }
        }
        return null
    }

    const visible = findVisibleStackedSegment({
        series: crossSeriesData.map((d) => d.series),
        labels,
        hoveredLabel: label,
        cursor,
        scales: d3Scales,
        layout: barLayout,
        isHorizontal,
        stackedData,
        topStackedKeyByAxis,
    })
    if (!visible) {
        return null
    }
    const hit = crossSeriesData.find((d) => d.series.key === visible.series.key)
    if (!hit) {
        return null
    }
    // Re-read value at the visible segment's own dataIndex — `hit.value` was resolved at the
    // band's dataIndex, which is a sparse-zero cell for the visible series.
    const raw = hit.series.data[visible.dataIndex]
    const resolvedValue = typeof raw === 'number' && Number.isFinite(raw) ? raw : hit.value
    return rewrite(hit.series, resolvedValue, visible.dataIndex)
}

import { computeBarAtIndex } from '../../../core/bar-layout'
import type { ComboScaleSet } from '../../../core/combo-scales'
import { resolveSeriesType } from '../../../core/combo-scales'
import type { BarScaleSet, StackedBand } from '../../../core/scales'
import type { Series, SeriesType } from '../../../core/types'
import { DEFAULT_Y_AXIS_ID } from '../../../core/types'
import { barContainsPointOnBandAxis } from '../../BarChart/utils/bars-under-cursor'

export interface BarKeysAtCursorArgs {
    series: readonly Pick<Series, 'key' | 'visibility' | 'yAxisId' | 'data' | 'type'>[]
    label: string
    dataIndex: number
    cursor: { x: number; y: number }
    scales: ComboScaleSet
    layout: 'stacked' | 'grouped'
    barStackedData?: Map<string, StackedBand>
    topStackedKeyByAxis: Map<string, string>
    defaultSeriesType: SeriesType
}

/** Bar-only band-axis hit-test for the combo chart. Mirrors {@link
 *  ../BarChart/utils/bars-under-cursor.seriesKeysAtCursor} but uses the per-axis value scale
 *  from the combo scale set and skips non-bar series (lines/areas are not band-positioned). */
export function barKeysAtCursor(args: BarKeysAtCursorArgs): Set<string> {
    const { series, label, dataIndex, cursor, scales, layout, barStackedData, topStackedKeyByAxis, defaultSeriesType } =
        args
    const hits = new Set<string>()
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        if (resolveSeriesType(s, defaultSeriesType) !== 'bar') {
            continue
        }
        const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
        const valueScale = scales.yAxes[axisId]?.scale ?? scales.y
        const perSeriesScales: BarScaleSet = { band: scales.band, value: valueScale, group: scales.group }
        const stackedBand = barStackedData?.get(s.key)
        const isTopOfStack = topStackedKeyByAxis.get(axisId) === s.key
        const bar = computeBarAtIndex({
            series: s as Series,
            label,
            dataIndex,
            scales: perSeriesScales,
            layout,
            isHorizontal: false,
            stackedBand,
            isTopOfStack,
        })
        if (bar && barContainsPointOnBandAxis(bar, cursor, false)) {
            hits.add(s.key)
        }
    }
    return hits
}

import * as d3 from 'd3'
import { useMemo } from 'react'

import { measureLabelWidth } from '../../overlays/AxisLabels'
import { autoFormatterFor, seriesValueRange } from '../scales'
import { DEFAULT_Y_AXIS_ID } from '../types'
import type { ChartMargins, Series } from '../types'

export const DEFAULT_MARGINS: ChartMargins = { top: 16, right: 16, bottom: 32, left: 48 }

interface UseChartMarginsOptions<Meta> {
    series: Series<Meta>[]
    labels: string[]
    hideXAxis: boolean
    hideYAxis: boolean
    xTickFormatter?: (value: string, index: number) => string | null
    yTickFormatter?: (value: number) => string
}

export function useChartMargins<Meta>({
    series,
    labels,
    hideXAxis,
    hideYAxis,
    xTickFormatter,
    yTickFormatter,
}: UseChartMarginsOptions<Meta>): ChartMargins {
    const hasMultipleAxes = useMemo(() => {
        const axisIds = new Set(
            series.filter((s) => !s.visibility?.excluded).map((s) => s.yAxisId ?? DEFAULT_Y_AXIS_ID)
        )
        return axisIds.size > 1
    }, [series])

    const yLabelWidth = useMemo<number>(() => {
        if (hideYAxis) {
            return 0
        }
        const range = seriesValueRange(series)
        if (range.count === 0) {
            return 0
        }
        const min = range.min > 0 ? 0 : range.min
        const max = range.max < 0 ? 0 : range.max
        const ticks = d3.scaleLinear().domain([min, max]).nice(6).ticks(6)
        if (ticks.length === 0) {
            return 0
        }
        const formatter = yTickFormatter ?? autoFormatterFor(ticks)
        let widest = 0
        for (const t of ticks) {
            widest = Math.max(widest, measureLabelWidth(formatter(t)))
        }
        return widest
    }, [series, yTickFormatter, hideYAxis])

    const xLabelHalfWidth = useMemo<number>(() => {
        if (hideXAxis || labels.length === 0) {
            return 0
        }
        let widest = 0
        for (let i = 0; i < labels.length; i++) {
            const text = xTickFormatter ? xTickFormatter(labels[i], i) : labels[i]
            if (text === null) {
                continue
            }
            widest = Math.max(widest, measureLabelWidth(text))
        }
        return Math.ceil(widest / 2)
    }, [labels, xTickFormatter, hideXAxis])

    return useMemo<ChartMargins>(() => {
        const m = { ...DEFAULT_MARGINS }
        if (hideXAxis) {
            m.bottom = 8
        }
        if (hideYAxis) {
            m.left = 8
        } else {
            m.left = Math.max(20, Math.ceil(yLabelWidth) + 12, xLabelHalfWidth + 4)
        }
        if (hasMultipleAxes && !hideYAxis) {
            m.right = Math.max(48, xLabelHalfWidth + 4)
        } else {
            m.right = Math.max(DEFAULT_MARGINS.right, xLabelHalfWidth + 4)
        }
        return m
    }, [hideXAxis, hideYAxis, hasMultipleAxes, yLabelWidth, xLabelHalfWidth])
}

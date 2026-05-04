import * as d3 from 'd3'
import { useMemo } from 'react'

import { measureLabelWidth } from '../../overlays/AxisLabels'
import { autoFormatterFor, seriesValueRange } from '../scales'
import { DEFAULT_Y_AXIS_ID } from '../types'
import type { ChartMargins, Series } from '../types'

export const DEFAULT_MARGINS: ChartMargins = { top: 16, right: 16, bottom: 32, left: 48 }

const COLLAPSED_AXIS_MARGIN = 8
const MIN_LEFT_MARGIN = 20
const MIN_RIGHT_MARGIN_DUAL_AXIS = 48
const Y_LABEL_RIGHT_PADDING = 12
const X_LABEL_EDGE_PADDING = 4

interface UseChartMarginsOptions {
    series: Series[]
    labels: string[]
    hideXAxis: boolean
    hideYAxis: boolean
    xTickFormatter?: (value: string, index: number) => string | null
    yTickFormatter?: (value: number) => string
    axisOrientation?: 'vertical' | 'horizontal'
}

function widestCategoryLabelWidth(
    labels: string[],
    xTickFormatter: ((value: string, index: number) => string | null) | undefined
): number {
    let widest = 0
    for (let i = 0; i < labels.length; i++) {
        const text = xTickFormatter ? xTickFormatter(labels[i], i) : labels[i]
        if (text === null) {
            continue
        }
        widest = Math.max(widest, measureLabelWidth(text))
    }
    return widest
}

function widestValueLabelWidth(series: Series[], yTickFormatter: ((value: number) => string) | undefined): number {
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
}

export function useChartMargins({
    series,
    labels,
    hideXAxis,
    hideYAxis,
    xTickFormatter,
    yTickFormatter,
    axisOrientation = 'vertical',
}: UseChartMarginsOptions): ChartMargins {
    const isHorizontal = axisOrientation === 'horizontal'

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
        if (isHorizontal) {
            return widestCategoryLabelWidth(labels, xTickFormatter)
        }
        return widestValueLabelWidth(series, yTickFormatter)
    }, [series, yTickFormatter, hideYAxis, isHorizontal, labels, xTickFormatter])

    const xLabelHalfWidth = useMemo<number>(() => {
        if (hideXAxis) {
            return 0
        }
        if (isHorizontal) {
            const widest = widestValueLabelWidth(series, yTickFormatter)
            return Math.ceil(widest / 2)
        }
        if (labels.length === 0) {
            return 0
        }
        return Math.ceil(widestCategoryLabelWidth(labels, xTickFormatter) / 2)
    }, [labels, xTickFormatter, hideXAxis, isHorizontal, series, yTickFormatter])

    return useMemo<ChartMargins>(() => {
        const bottom = hideXAxis ? COLLAPSED_AXIS_MARGIN : DEFAULT_MARGINS.bottom
        const left = hideYAxis
            ? COLLAPSED_AXIS_MARGIN
            : Math.max(
                  MIN_LEFT_MARGIN,
                  Math.ceil(yLabelWidth) + Y_LABEL_RIGHT_PADDING,
                  xLabelHalfWidth + X_LABEL_EDGE_PADDING
              )
        const rightFloor = hasMultipleAxes && !hideYAxis ? MIN_RIGHT_MARGIN_DUAL_AXIS : DEFAULT_MARGINS.right
        const right = Math.max(rightFloor, xLabelHalfWidth + X_LABEL_EDGE_PADDING)
        return { top: DEFAULT_MARGINS.top, right, bottom, left }
    }, [hideXAxis, hideYAxis, hasMultipleAxes, yLabelWidth, xLabelHalfWidth])
}

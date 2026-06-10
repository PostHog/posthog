import { scaleLinear } from 'd3-scale'
import { useMemo } from 'react'

import { normalizeAxisLabel } from '../../utils/axis-labels'
import { measureLabelWidth } from '../../utils/text-measure'
import { autoFormatterFor, orderedAxisPositions, seriesValueRange } from '../scales'
import { DEFAULT_Y_AXIS_ID } from '../types'
import type { ChartMargins, Series } from '../types'

export const DEFAULT_MARGINS: ChartMargins = { top: 16, right: 16, bottom: 32, left: 48 }

const COLLAPSED_AXIS_MARGIN = 8
const MIN_LEFT_MARGIN = 20
const MIN_RIGHT_MARGIN_DUAL_AXIS = 48
const Y_LABEL_RIGHT_PADDING = 12
// Gutter left of the y-axis labels so the widest label doesn't sit flush at the plot's left edge
// and clip against the chart wrapper's `overflow: hidden`.
const Y_LABEL_LEFT_GUTTER = 6
/** Horizontal gap between stacked value-axis gutters on the same side — shared by the margin
 *  reservation here and the gutter rendering in AxisLabels so the two can't drift. */
export const GUTTER_GAP = 12
const X_LABEL_EDGE_PADDING = 4
export const X_AXIS_TITLE_MARGIN = 22
const Y_AXIS_TITLE_MARGIN = 24

interface UseChartMarginsOptions {
    series: Series[]
    labels: string[]
    hideXAxis: boolean
    hideYAxis: boolean
    xAxisLabel?: string
    yAxisLabel?: string
    xTickFormatter?: (value: string, index: number) => string | null
    yTickFormatter?: (value: number) => string
    axisOrientation?: 'vertical' | 'horizontal'
    /** Per-side overrides applied on top of the computed margins. */
    override?: Partial<ChartMargins>
    /** Override the value-range source for value-axis tick sizing. Defaults to `series`. Use
     *  this when the visible series's `data[i]` doesn't span the full y-domain — e.g. BoxPlot
     *  passes the whisker min/max samples so the y-tick column fits the actual range, not just
     *  the medians it draws on `series.data`. yAxis-id discovery still reads from `series`. */
    valueRangeSeries?: Series[]
    /** When set, clamp the reserved category-label width to this ceiling so a single long label
     *  can't grow the axis margin without bound. Mirrors AxisLabels' display truncation. */
    maxCategoryLabelWidth?: number
}

function widestCategoryLabelWidth(
    labels: string[],
    xTickFormatter: ((value: string, index: number) => string | null) | undefined,
    maxCategoryLabelWidth = 0
): number {
    let widest = 0
    for (let i = 0; i < labels.length; i++) {
        const text = xTickFormatter ? xTickFormatter(labels[i], i) : labels[i]
        if (text === null) {
            continue
        }
        widest = Math.max(widest, measureLabelWidth(text))
    }
    return maxCategoryLabelWidth > 0 ? Math.min(widest, maxCategoryLabelWidth) : widest
}

function widestValueLabelWidth(series: Series[], yTickFormatter: ((value: number) => string) | undefined): number {
    const range = seriesValueRange(series)
    if (range.count === 0) {
        return 0
    }
    const min = range.min > 0 ? 0 : range.min
    const max = range.max < 0 ? 0 : range.max
    const ticks = scaleLinear().domain([min, max]).nice(6).ticks(6)
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
    xAxisLabel,
    yAxisLabel,
    xTickFormatter,
    yTickFormatter,
    axisOrientation = 'vertical',
    override,
    valueRangeSeries,
    maxCategoryLabelWidth = 0,
}: UseChartMarginsOptions): ChartMargins {
    const isHorizontal = axisOrientation === 'horizontal'
    const valueSeries = valueRangeSeries ?? series
    const normalizedXAxisLabel = normalizeAxisLabel(xAxisLabel)
    const normalizedYAxisLabel = normalizeAxisLabel(yAxisLabel)

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
            return widestCategoryLabelWidth(labels, xTickFormatter, maxCategoryLabelWidth)
        }
        return widestValueLabelWidth(valueSeries, yTickFormatter)
    }, [valueSeries, yTickFormatter, hideYAxis, isHorizontal, labels, xTickFormatter, maxCategoryLabelWidth])

    const xLabelHalfWidth = useMemo<number>(() => {
        if (hideXAxis) {
            return 0
        }
        if (isHorizontal) {
            const widest = widestValueLabelWidth(valueSeries, yTickFormatter)
            return Math.ceil(widest / 2)
        }
        if (labels.length === 0) {
            return 0
        }
        return Math.ceil(widestCategoryLabelWidth(labels, xTickFormatter, maxCategoryLabelWidth) / 2)
    }, [labels, xTickFormatter, hideXAxis, isHorizontal, valueSeries, yTickFormatter, maxCategoryLabelWidth])

    // With multiple y-axes the value-axis labels stack into several gutters per side; reserve the
    // cumulative width so the outer gutters aren't clipped. Mirrors AxisLabels' gutter layout.
    const gutterReserves = useMemo<{ left: number; right: number } | null>(() => {
        if (hideYAxis || isHorizontal || !hasMultipleAxes) {
            return null
        }
        const byAxis = new Map<string, Series[]>()
        for (const s of valueSeries) {
            if (s.visibility?.excluded) {
                continue
            }
            const id = s.yAxisId ?? DEFAULT_Y_AXIS_ID
            const bucket = byAxis.get(id)
            if (bucket) {
                bucket.push(s)
            } else {
                byAxis.set(id, [s])
            }
        }
        let left = 0
        let right = 0
        for (const { axisId, position } of orderedAxisPositions(valueSeries)) {
            const width = Math.ceil(widestValueLabelWidth(byAxis.get(axisId) ?? [], yTickFormatter)) + Y_LABEL_RIGHT_PADDING
            if (position === 'left') {
                left += width + (left > 0 ? GUTTER_GAP : 0)
            } else {
                right += width + (right > 0 ? GUTTER_GAP : 0)
            }
        }
        return { left, right }
    }, [hideYAxis, isHorizontal, hasMultipleAxes, valueSeries, yTickFormatter])

    return useMemo<ChartMargins>(() => {
        const bottom = hideXAxis
            ? COLLAPSED_AXIS_MARGIN
            : DEFAULT_MARGINS.bottom + (normalizedXAxisLabel ? X_AXIS_TITLE_MARGIN : 0)
        const leftLabelReserve = gutterReserves ? gutterReserves.left : Math.ceil(yLabelWidth) + Y_LABEL_RIGHT_PADDING
        const left = hideYAxis
            ? COLLAPSED_AXIS_MARGIN
            : Math.max(MIN_LEFT_MARGIN, leftLabelReserve + Y_LABEL_LEFT_GUTTER, xLabelHalfWidth + X_LABEL_EDGE_PADDING) +
              (normalizedYAxisLabel ? Y_AXIS_TITLE_MARGIN : 0)
        const rightFloor = hasMultipleAxes && !hideYAxis ? MIN_RIGHT_MARGIN_DUAL_AXIS : DEFAULT_MARGINS.right
        const right = Math.max(rightFloor, gutterReserves?.right ?? 0, xLabelHalfWidth + X_LABEL_EDGE_PADDING)
        const computed: ChartMargins = { top: DEFAULT_MARGINS.top, right, bottom, left }
        return override ? { ...computed, ...override } : computed
    }, [
        hideXAxis,
        hideYAxis,
        hasMultipleAxes,
        gutterReserves,
        yLabelWidth,
        xLabelHalfWidth,
        normalizedXAxisLabel,
        normalizedYAxisLabel,
        override,
    ])
}

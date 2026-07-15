import { scaleLinear } from 'd3-scale'
import { useMemo } from 'react'

import {
    AXIS_TICK_LABEL_HEIGHT,
    normalizeAxisLabel,
    normalizeTickLabelRotation,
    rotatedTickLabelSize,
} from '../../utils/axis-labels'
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
export const Y_AXIS_TITLE_MARGIN = 24

interface UseChartMarginsOptions {
    series: Series[]
    labels: string[]
    hideXAxis: boolean
    hideYAxis: boolean
    xAxisLabel?: string
    xTickFormatter?: (value: string, index: number) => string | null
    xTickLabelRotation?: number
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
    /** Per-axis tick formatters keyed by axis id, for sizing each gutter against its own labels.
     *  Falls back to `yTickFormatter` for axes not listed. Multi-axis charts only. */
    yAxisFormatters?: Record<string, (value: number) => string>
    /** Per-axis sides keyed by axis id, overriding the alternating-side default. Keeps the margin
     *  reservation in step with the scales' config-driven positions. Multi-axis charts only. */
    yAxisPositions?: Record<string, 'left' | 'right'>
    yAxisTitles?: Record<string, string>
    /** Axis ids whose gutters are hidden — no margin reserved. Mirrors `computeYAxisGutters`. */
    yAxisHidden?: Record<string, boolean>
}

interface CategoryLabelWidths {
    first: number
    last: number
    widest: number
}

function categoryLabelWidths(
    labels: string[],
    xTickFormatter: ((value: string, index: number) => string | null) | undefined,
    maxCategoryLabelWidth = 0
): CategoryLabelWidths {
    const widths: number[] = []
    for (let i = 0; i < labels.length; i++) {
        const text = xTickFormatter ? xTickFormatter(labels[i], i) : labels[i]
        if (text === null) {
            continue
        }
        const measured = measureLabelWidth(text)
        widths.push(maxCategoryLabelWidth > 0 ? Math.min(measured, maxCategoryLabelWidth) : measured)
    }
    return {
        first: widths[0] ?? 0,
        last: widths.at(-1) ?? 0,
        widest: Math.max(0, ...widths),
    }
}

function widestValueLabelWidth(series: Series[], yTickFormatter: ((value: number) => string) | undefined): number {
    const range = seriesValueRange(series)
    // No data: the scale falls back to a [0, 1] domain (see `buildValueScale`), whose ticks render
    // as "0.00".."1.00". Measure those so the empty-state margin still fits its labels — returning 0
    // here collapses the margin to its floor and clips the labels against the wrapper's overflow.
    const [min, max] = range.count === 0 ? [0, 1] : [range.min > 0 ? 0 : range.min, range.max < 0 ? 0 : range.max]
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
    xTickFormatter,
    xTickLabelRotation = 0,
    yTickFormatter,
    axisOrientation = 'vertical',
    override,
    valueRangeSeries,
    maxCategoryLabelWidth = 0,
    yAxisFormatters,
    yAxisPositions,
    yAxisTitles,
    yAxisHidden,
}: UseChartMarginsOptions): ChartMargins {
    const isHorizontal = axisOrientation === 'horizontal'
    const valueSeries = valueRangeSeries ?? series
    const normalizedXAxisLabel = normalizeAxisLabel(xAxisLabel)
    const tickLabelRotation = isHorizontal ? 0 : normalizeTickLabelRotation(xTickLabelRotation)
    const categoryWidths = useMemo(
        () => categoryLabelWidths(labels, xTickFormatter, maxCategoryLabelWidth),
        [labels, xTickFormatter, maxCategoryLabelWidth]
    )

    const hasMultipleAxes = useMemo(() => {
        const axisIds = new Set(
            series.filter((s) => !s.visibility?.excluded).map((s) => s.yAxisId ?? DEFAULT_Y_AXIS_ID)
        )
        return axisIds.size > 1
    }, [series])

    // Per-side gutter layout also applies to a single axis explicitly pinned right — the series-count
    // check above misses it, which would reserve the left margin while the gutter draws on the right.
    const usesPerSideGutters = useMemo(
        () => hasMultipleAxes || Object.values(yAxisPositions ?? {}).some((side) => side === 'right'),
        [hasMultipleAxes, yAxisPositions]
    )

    // One rotated-title band per titled axis, on its side. Horizontal charts (category axis on the
    // left) and single-value-axis charts only ever title the default left axis.
    const titleReserve = useMemo<{ left: number; right: number }>(() => {
        if (hideYAxis || !yAxisTitles) {
            return { left: 0, right: 0 }
        }
        if (isHorizontal || !usesPerSideGutters) {
            return { left: yAxisTitles[DEFAULT_Y_AXIS_ID] ? Y_AXIS_TITLE_MARGIN : 0, right: 0 }
        }
        let left = 0
        let right = 0
        for (const { axisId, position } of orderedAxisPositions(valueSeries)) {
            if (!yAxisTitles[axisId] || yAxisHidden?.[axisId]) {
                continue
            }
            if ((yAxisPositions?.[axisId] ?? position) === 'left') {
                left += Y_AXIS_TITLE_MARGIN
            } else {
                right += Y_AXIS_TITLE_MARGIN
            }
        }
        return { left, right }
    }, [hideYAxis, isHorizontal, usesPerSideGutters, valueSeries, yAxisPositions, yAxisTitles, yAxisHidden])

    const yLabelWidth = useMemo<number>(() => {
        if (hideYAxis) {
            return 0
        }
        if (isHorizontal) {
            return categoryWidths.widest
        }
        return widestValueLabelWidth(valueSeries, yTickFormatter)
    }, [valueSeries, yTickFormatter, hideYAxis, isHorizontal, categoryWidths.widest])

    const xLabelEdgeReserves = useMemo<{ left: number; right: number }>(() => {
        if (hideXAxis) {
            return { left: 0, right: 0 }
        }
        if (isHorizontal) {
            const widest = widestValueLabelWidth(valueSeries, yTickFormatter)
            const halfWidth = Math.ceil(widest / 2)
            return { left: halfWidth, right: halfWidth }
        }
        if (labels.length === 0) {
            return { left: 0, right: 0 }
        }
        if (tickLabelRotation === 0) {
            const halfWidth = Math.ceil(categoryWidths.widest / 2)
            return { left: halfWidth, right: halfWidth }
        }

        const radians = (Math.abs(tickLabelRotation) * Math.PI) / 180
        const thinEdgeReserve = Math.ceil(AXIS_TICK_LABEL_HEIGHT * Math.sin(radians))
        if (tickLabelRotation < 0) {
            return {
                left: Math.ceil(categoryWidths.first * Math.cos(radians)),
                right: thinEdgeReserve,
            }
        }
        return {
            left: thinEdgeReserve,
            right: Math.ceil(categoryWidths.last * Math.cos(radians)),
        }
    }, [categoryWidths, hideXAxis, isHorizontal, labels.length, tickLabelRotation, valueSeries, yTickFormatter])

    const xLabelExtraBottom = useMemo<number>(() => {
        if (hideXAxis || isHorizontal || tickLabelRotation === 0) {
            return 0
        }
        const rotatedHeight = rotatedTickLabelSize(categoryWidths.widest, tickLabelRotation).height
        return Math.max(0, Math.ceil(rotatedHeight - AXIS_TICK_LABEL_HEIGHT))
    }, [categoryWidths.widest, hideXAxis, isHorizontal, tickLabelRotation])

    // With multiple y-axes the value-axis labels stack into several gutters per side; reserve the
    // cumulative width so the outer gutters aren't clipped. Mirrors AxisLabels' gutter layout.
    const gutterReserves = useMemo<{ left: number; right: number } | null>(() => {
        if (hideYAxis || isHorizontal || !usesPerSideGutters) {
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
            if (yAxisHidden?.[axisId]) {
                continue
            }
            const formatter = yAxisFormatters?.[axisId] ?? yTickFormatter
            const side = yAxisPositions?.[axisId] ?? position
            const width = Math.ceil(widestValueLabelWidth(byAxis.get(axisId) ?? [], formatter)) + Y_LABEL_RIGHT_PADDING
            if (side === 'left') {
                left += width + (left > 0 ? GUTTER_GAP : 0)
            } else {
                right += width + (right > 0 ? GUTTER_GAP : 0)
            }
        }
        return { left, right }
    }, [
        hideYAxis,
        isHorizontal,
        usesPerSideGutters,
        valueSeries,
        yTickFormatter,
        yAxisFormatters,
        yAxisPositions,
        yAxisHidden,
    ])

    return useMemo<ChartMargins>(() => {
        const bottom = hideXAxis
            ? COLLAPSED_AXIS_MARGIN
            : DEFAULT_MARGINS.bottom + xLabelExtraBottom + (normalizedXAxisLabel ? X_AXIS_TITLE_MARGIN : 0)
        const leftLabelReserve = gutterReserves ? gutterReserves.left : Math.ceil(yLabelWidth) + Y_LABEL_RIGHT_PADDING
        const left = hideYAxis
            ? COLLAPSED_AXIS_MARGIN
            : Math.max(
                  MIN_LEFT_MARGIN,
                  leftLabelReserve + Y_LABEL_LEFT_GUTTER,
                  xLabelEdgeReserves.left + X_LABEL_EDGE_PADDING
              ) + titleReserve.left
        const rightFloor = usesPerSideGutters && !hideYAxis ? MIN_RIGHT_MARGIN_DUAL_AXIS : DEFAULT_MARGINS.right
        const rightLabelReserve = (gutterReserves?.right ?? 0) + titleReserve.right
        const right = Math.max(rightFloor, rightLabelReserve, xLabelEdgeReserves.right + X_LABEL_EDGE_PADDING)
        const computed: ChartMargins = { top: DEFAULT_MARGINS.top, right, bottom, left }
        return override ? { ...computed, ...override } : computed
    }, [
        hideXAxis,
        hideYAxis,
        usesPerSideGutters,
        gutterReserves,
        yLabelWidth,
        xLabelEdgeReserves,
        xLabelExtraBottom,
        normalizedXAxisLabel,
        titleReserve,
        override,
    ])
}

import { scaleLinear } from 'd3-scale'
import { useMemo } from 'react'

import {
    AXIS_TICK_LABEL_HEIGHT,
    normalizeAxisLabel,
    normalizeTickLabelRotation,
    rotatedTickLabelSize,
} from '../../utils/axis-labels'
import { measureLabelWidth } from '../../utils/text-measure'
import { autoFormatterFor, groupVisibleSeriesByAxis, orderedAxisPositions, seriesValueRange } from '../scales'
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
/** Breathing room past half an edge tick label, so the outermost label doesn't sit flush against
 *  the wrapper's clip. Shared with chart types that reserve their own x-label gutters. */
export const X_LABEL_EDGE_PADDING = 4
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
    /** Percent layouts plot every series on a [0, 1] domain, so tick sizing ignores the raw values. */
    isPercent?: boolean
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

/** Apply per-side overrides, skipping sides left `undefined`. A plain spread would write the
 *  `undefined` through and clobber the computed margin, which turns the whole plot geometry into
 *  `NaN` and renders a blank chart — so a caller building an override object conditionally
 *  (`{ top: reserveOrUndefined }`) gets "leave this side alone" rather than a silent wipeout. */
export function applyMarginOverride(computed: ChartMargins, override: Partial<ChartMargins>): ChartMargins
export function applyMarginOverride(
    computed: Partial<ChartMargins>,
    override: Partial<ChartMargins>
): Partial<ChartMargins>
export function applyMarginOverride(
    computed: Partial<ChartMargins>,
    override: Partial<ChartMargins>
): Partial<ChartMargins> {
    const result = { ...computed }
    for (const side of ['top', 'right', 'bottom', 'left'] as const) {
        const value = override[side]
        if (value !== undefined) {
            result[side] = value
        }
    }
    return result
}

/** Rebuilds a margin override from its four sides, so an inline `margins` object with the same values
 *  keeps one identity and does not re-run the memos that read it. */
export function useStableMargins(margins: Partial<ChartMargins> | undefined): Partial<ChartMargins> {
    const { top, right, bottom, left } = margins ?? {}
    return useMemo(() => ({ top, right, bottom, left }), [top, right, bottom, left])
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
    // Track first/last/widest in one pass — spreading a per-label array into `Math.max`
    // can overflow the argument limit on a high-cardinality category axis.
    let first = 0
    let last = 0
    let widest = 0
    let seenAny = false
    for (let i = 0; i < labels.length; i++) {
        const text = xTickFormatter ? xTickFormatter(labels[i], i) : labels[i]
        if (text === null) {
            continue
        }
        const measured = measureLabelWidth(text)
        const width = maxCategoryLabelWidth > 0 ? Math.min(measured, maxCategoryLabelWidth) : measured
        if (!seenAny) {
            first = width
            seenAny = true
        }
        last = width
        if (width > widest) {
            widest = width
        }
    }
    return { first, last, widest }
}

function widestValueLabelWidth(
    series: Series[],
    yTickFormatter: ((value: number) => string) | undefined,
    isPercent: boolean
): number {
    const range = isPercent ? null : seriesValueRange(series)
    // No data: the scale falls back to a [0, 1] domain (see `buildValueScale`), whose automatic ticks
    // render as "0".."1". Measure those so the empty-state margin still fits its labels — returning 0
    // here collapses the margin to its floor and clips the labels against the wrapper's overflow.
    const [min, max] =
        !range || range.count === 0 ? [0, 1] : [range.min > 0 ? 0 : range.min, range.max < 0 ? 0 : range.max]
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

interface SideReserve {
    left: number
    right: number
}

const NO_RESERVE: SideReserve = { left: 0, right: 0 }

interface PerAxisOptions {
    rangeSeries: Series[]
    isPercent: boolean
    yTickFormatter?: (value: number) => string
    yAxisFormatters?: Record<string, (value: number) => string>
    yAxisPositions?: Record<string, 'left' | 'right'>
    yAxisTitles?: Record<string, string>
    yAxisHidden?: Record<string, boolean>
}

// Mirrors AxisLabels' gutter layout.
function perAxisReserves(options: PerAxisOptions): { gutters: SideReserve; titles: SideReserve } {
    const { rangeSeries, isPercent, yTickFormatter, yAxisFormatters, yAxisPositions, yAxisTitles, yAxisHidden } =
        options
    const byAxis = groupVisibleSeriesByAxis(rangeSeries)
    const gutters = { left: 0, right: 0 }
    const titles = { left: 0, right: 0 }
    for (const { axisId, position } of orderedAxisPositions(rangeSeries)) {
        if (yAxisHidden?.[axisId]) {
            continue
        }
        const side = yAxisPositions?.[axisId] ?? position
        const formatter = yAxisFormatters?.[axisId] ?? yTickFormatter
        const width = Math.ceil(widestValueLabelWidth(byAxis.get(axisId) ?? [], formatter, isPercent))
        gutters[side] += width + Y_LABEL_RIGHT_PADDING + (gutters[side] > 0 ? GUTTER_GAP : 0)
        titles[side] += yAxisTitles?.[axisId] ? Y_AXIS_TITLE_MARGIN : 0
    }
    return { gutters, titles }
}

function categoryEdgeReserves(categoryWidths: CategoryLabelWidths, tickLabelRotation: number): SideReserve {
    if (tickLabelRotation === 0) {
        const halfWidth = Math.ceil(categoryWidths.widest / 2)
        return { left: halfWidth, right: halfWidth }
    }
    const radians = (Math.abs(tickLabelRotation) * Math.PI) / 180
    const thinEdgeReserve = Math.ceil(AXIS_TICK_LABEL_HEIGHT * Math.sin(radians))
    if (tickLabelRotation < 0) {
        return { left: Math.ceil(categoryWidths.first * Math.cos(radians)), right: thinEdgeReserve }
    }
    return { left: thinEdgeReserve, right: Math.ceil(categoryWidths.last * Math.cos(radians)) }
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
    isPercent = false,
    override,
    valueRangeSeries,
    maxCategoryLabelWidth = 0,
    yAxisFormatters,
    yAxisPositions,
    yAxisTitles,
    yAxisHidden,
}: UseChartMarginsOptions): ChartMargins {
    const isHorizontal = axisOrientation === 'horizontal'
    const rangeSeries = isPercent ? series : (valueRangeSeries ?? series)
    const tickLabelRotation = isHorizontal ? 0 : normalizeTickLabelRotation(xTickLabelRotation)
    // A single axis pinned right draws its gutter on the right, so it needs the per-side layout too.
    const usesPerSideGutters =
        orderedAxisPositions(series).length > 1 || Object.values(yAxisPositions ?? {}).includes('right')
    const perAxis = !hideYAxis && !isHorizontal && usesPerSideGutters
    const needsWidestValue = isHorizontal ? !hideXAxis : !hideYAxis && !perAxis

    const categoryWidths = useMemo(
        () => categoryLabelWidths(labels, xTickFormatter, maxCategoryLabelWidth),
        [labels, xTickFormatter, maxCategoryLabelWidth]
    )
    const widestValue = useMemo(
        () => (needsWidestValue ? widestValueLabelWidth(rangeSeries, yTickFormatter, isPercent) : 0),
        [needsWidestValue, rangeSeries, yTickFormatter, isPercent]
    )
    const perAxisWidths = useMemo(
        () =>
            perAxis
                ? perAxisReserves({
                      rangeSeries,
                      isPercent,
                      yTickFormatter,
                      yAxisFormatters,
                      yAxisPositions,
                      yAxisTitles,
                      yAxisHidden,
                  })
                : null,
        [perAxis, rangeSeries, isPercent, yTickFormatter, yAxisFormatters, yAxisPositions, yAxisTitles, yAxisHidden]
    )

    const defaultTitle = !hideYAxis && yAxisTitles?.[DEFAULT_Y_AXIS_ID] ? Y_AXIS_TITLE_MARGIN : 0
    const titles = perAxisWidths?.titles ?? { left: defaultTitle, right: 0 }

    let xLabelEdges = NO_RESERVE
    if (!hideXAxis && isHorizontal) {
        xLabelEdges = { left: Math.ceil(widestValue / 2), right: Math.ceil(widestValue / 2) }
    } else if (!hideXAxis && labels.length > 0) {
        xLabelEdges = categoryEdgeReserves(categoryWidths, tickLabelRotation)
    }

    let bottom = COLLAPSED_AXIS_MARGIN
    if (!hideXAxis) {
        const rotatedHeight =
            tickLabelRotation === 0 ? 0 : rotatedTickLabelSize(categoryWidths.widest, tickLabelRotation).height
        const extraBottom = Math.max(0, Math.ceil(rotatedHeight - AXIS_TICK_LABEL_HEIGHT))
        bottom = DEFAULT_MARGINS.bottom + extraBottom + (normalizeAxisLabel(xAxisLabel) ? X_AXIS_TITLE_MARGIN : 0)
    }

    const yLabelWidth = isHorizontal ? categoryWidths.widest : widestValue
    const leftLabelReserve = perAxisWidths?.gutters.left ?? Math.ceil(yLabelWidth) + Y_LABEL_RIGHT_PADDING
    // The first x label overhangs the plot's left edge even with the y-axis hidden.
    const left = hideYAxis
        ? Math.max(COLLAPSED_AXIS_MARGIN, xLabelEdges.left + X_LABEL_EDGE_PADDING)
        : Math.max(MIN_LEFT_MARGIN, leftLabelReserve + Y_LABEL_LEFT_GUTTER, xLabelEdges.left + X_LABEL_EDGE_PADDING) +
          titles.left
    const rightFloor = usesPerSideGutters && !hideYAxis ? MIN_RIGHT_MARGIN_DUAL_AXIS : DEFAULT_MARGINS.right
    const rightLabelReserve = (perAxisWidths?.gutters.right ?? 0) + titles.right
    const right = Math.max(rightFloor, rightLabelReserve, xLabelEdges.right + X_LABEL_EDGE_PADDING)

    const margins = applyMarginOverride({ top: DEFAULT_MARGINS.top, right, bottom, left }, override ?? {})
    return useMemo(
        () => ({ top: margins.top, right: margins.right, bottom: margins.bottom, left: margins.left }),
        [margins.top, margins.right, margins.bottom, margins.left]
    )
}

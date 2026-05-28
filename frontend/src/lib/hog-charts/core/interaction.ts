import { bisector } from 'd3'

import type {
    ChartDimensions,
    PointClickData,
    ResolvedSeries,
    ResolveValueFn,
    TooltipContext,
    YAxisScale,
} from './types'
import { DEFAULT_Y_AXIS_ID } from './types'

export interface LabelPosition {
    x: number
    index: number
}

const positionBisector = bisector<LabelPosition, number>((d) => d.x).center

/** Builds the (x, index) lookup table for hit-testing. O(N) — call once per (labels, xScale) change
 *  and feed the result into {@link findNearestIndexFromPositions} on each mousemove. */
export function buildLabelPositions(labels: string[], xScale: (label: string) => number | undefined): LabelPosition[] {
    const positions: LabelPosition[] = []
    for (let i = 0; i < labels.length; i++) {
        const x = xScale(labels[i])
        if (x != null && isFinite(x)) {
            positions.push({ x, index: i })
        }
    }
    return positions
}

/** Binary search over precomputed positions. O(log N) per call. */
export function findNearestIndexFromPositions(mouseX: number, positions: LabelPosition[]): number {
    if (positions.length === 0) {
        return -1
    }
    const nearestIdx = positionBisector(positions, mouseX)
    return positions[Math.max(0, Math.min(nearestIdx, positions.length - 1))].index
}

export function findNearestIndex(
    mouseX: number,
    labels: string[],
    xScale: (label: string) => number | undefined
): number {
    if (labels.length === 0) {
        return -1
    }
    return findNearestIndexFromPositions(mouseX, buildLabelPositions(labels, xScale))
}

export function isInPlotArea(mouseX: number, mouseY: number, dimensions: ChartDimensions): boolean {
    return (
        mouseX >= dimensions.plotLeft &&
        mouseX <= dimensions.plotLeft + dimensions.plotWidth &&
        mouseY >= dimensions.plotTop &&
        mouseY <= dimensions.plotTop + dimensions.plotHeight
    )
}

export function buildTooltipContext<Meta = unknown>(
    dataIndex: number,
    series: ResolvedSeries<Meta>[],
    labels: string[],
    xScale: (label: string) => number | undefined,
    yScale: (value: number) => number,
    canvasBounds: DOMRect,
    resolveValue: ResolveValueFn,
    yAxes?: Record<string, YAxisScale>,
    /** Returned `position.{x,y}` are canvas-pixel coordinates regardless of orientation. */
    interactionAxis: 'x' | 'y' = 'x',
    hoverPosition: { x: number; y: number } | null = null,
    /** Resolves the value used to *anchor* the tooltip per series. Defaults to `resolveValue`.
     *  Stacked charts pass the stacked-top resolver here so the anchor lands at the visual top
     *  of each segment while each tooltip row still shows its own value via `resolveValue`. */
    resolvePositionValue: ResolveValueFn = resolveValue,
    /** Optional horizontal data-extent centered on the categorical axis position — bar charts
     *  pass band width so the tooltip can anchor at the band edge instead of its center. */
    positionExtent?: number
): TooltipContext<Meta> | null {
    if (dataIndex < 0 || dataIndex >= labels.length) {
        return null
    }

    const label = labels[dataIndex]
    const bandPixel = xScale(label)
    if (bandPixel == null) {
        return null
    }

    const seriesData: TooltipContext<Meta>['seriesData'] = []
    const valuePixels: number[] = []
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        // `resolveValue` is the value shown to the user (the segment); `resolvePositionValue`
        // is where to anchor (the stacked top). They diverge only for stacked charts.
        if (s.visibility?.tooltip !== false) {
            seriesData.push({ series: s, value: resolveValue(s, dataIndex), color: s.color })
        }
        const seriesValueScale = yAxes?.[s.yAxisId ?? DEFAULT_Y_AXIS_ID]?.scale ?? yScale
        const px = seriesValueScale(resolvePositionValue(s, dataIndex))
        if (isFinite(px)) {
            valuePixels.push(px)
        }
    }

    // Anchor at the visual "tip" of the data column at this hover index — topmost in vertical
    // mode, rightmost in horizontal mode.
    let valueAnchor = 0
    if (valuePixels.length > 0) {
        valueAnchor = interactionAxis === 'y' ? Math.max(...valuePixels) : Math.min(...valuePixels)
    }

    const position: TooltipContext<Meta>['position'] =
        interactionAxis === 'y' ? { x: valueAnchor, y: bandPixel } : { x: bandPixel, y: valueAnchor }
    if (positionExtent != null && positionExtent > 0) {
        position.width = positionExtent
    }

    return {
        dataIndex,
        label,
        seriesData,
        position,
        hoverPosition,
        canvasBounds,
        isPinned: false,
    }
}

export function buildPointClickData<Meta = unknown>(
    dataIndex: number,
    series: ResolvedSeries<Meta>[],
    labels: string[],
    resolveValue: ResolveValueFn
): PointClickData<Meta> | null {
    if (dataIndex < 0 || dataIndex >= labels.length) {
        return null
    }

    const visibleSeries = series.filter((s) => !s.visibility?.excluded)
    if (visibleSeries.length === 0) {
        return null
    }

    const firstSeries = visibleSeries[0]

    return {
        seriesIndex: series.indexOf(firstSeries),
        dataIndex,
        series: firstSeries,
        value: resolveValue(firstSeries, dataIndex),
        label: labels[dataIndex],
        crossSeriesData: visibleSeries.map((s) => ({
            series: s,
            value: resolveValue(s, dataIndex),
        })),
    }
}

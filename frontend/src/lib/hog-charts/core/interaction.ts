import { bisector } from 'd3'

import type { ChartDimensions, PointClickData, ResolveValueFn, Series, TooltipContext, YAxisScale } from './types'
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
    series: Series<Meta>[],
    labels: string[],
    xScale: (label: string) => number | undefined,
    yScale: (value: number) => number,
    canvasBounds: DOMRect,
    resolveValue: ResolveValueFn,
    yAxes?: Record<string, YAxisScale>
): TooltipContext<Meta> | null {
    if (dataIndex < 0 || dataIndex >= labels.length) {
        return null
    }

    const label = labels[dataIndex]
    const x = xScale(label)
    if (x == null) {
        return null
    }

    const seriesData: TooltipContext<Meta>['seriesData'] = []
    const yPixels: number[] = []
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        const value = resolveValue(s, dataIndex)
        if (!s.visibility?.fromTooltip) {
            seriesData.push({ series: s, value, color: s.color })
        }
        const seriesYScale = yAxes?.[s.yAxisId ?? DEFAULT_Y_AXIS_ID]?.scale ?? yScale
        const yVal = seriesYScale(value)
        if (isFinite(yVal)) {
            yPixels.push(yVal)
        }
    }

    const y = yPixels.length > 0 ? Math.min(...yPixels) : 0

    return {
        dataIndex,
        label,
        seriesData,
        position: { x, y },
        canvasBounds,
        isPinned: false,
    }
}

export function buildPointClickData<Meta = unknown>(
    dataIndex: number,
    series: Series<Meta>[],
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

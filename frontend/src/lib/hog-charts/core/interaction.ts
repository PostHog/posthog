import { bisector } from 'd3'

import type { ChartDimensions, PointClickData, ResolveValueFn, Series, TooltipContext } from './types'

export function findNearestIndex(
    mouseX: number,
    labels: string[],
    xScale: (label: string) => number | undefined
): number {
    if (labels.length === 0) {
        return -1
    }

    const positions: { x: number; index: number }[] = []
    for (let i = 0; i < labels.length; i++) {
        const x = xScale(labels[i]) ?? 0
        if (isFinite(x)) {
            positions.push({ x, index: i })
        }
    }

    if (positions.length === 0) {
        return -1
    }

    const bisect = bisector<{ x: number; index: number }, number>((d) => d.x).center
    const nearestIdx = bisect(positions, mouseX)
    return positions[Math.max(0, Math.min(nearestIdx, positions.length - 1))].index
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
    resolveValue: ResolveValueFn
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
        if (s.hidden) {
            continue
        }
        const value = resolveValue(s, dataIndex)
        seriesData.push({ series: s, value, color: s.color })
        const yVal = yScale(value)
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

    const visibleSeries = series.filter((s) => !s.hidden)
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

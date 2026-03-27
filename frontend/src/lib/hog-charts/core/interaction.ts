import { bisector } from 'd3'

import type { ChartDimensions, PointClickData, Series, TooltipContext } from './types'

export function findNearestIndex(
    mouseX: number,
    labels: string[],
    xScale: (label: string) => number | undefined
): number {
    if (labels.length === 0) {
        return -1
    }

    // Build sorted x-positions
    const positions = labels.map((label, i) => ({ x: xScale(label) ?? 0, index: i })).filter((p) => isFinite(p.x))

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

export function buildTooltipContext(
    dataIndex: number,
    series: Series[],
    labels: string[],
    xScale: (label: string) => number | undefined,
    yScale: (value: number) => number,
    canvasBounds: DOMRect,
    stackedData?: Map<string, number[]>
): TooltipContext | null {
    if (dataIndex < 0 || dataIndex >= labels.length) {
        return null
    }

    const label = labels[dataIndex]
    const x = xScale(label)
    if (x == null) {
        return null
    }

    const seriesData = series
        .filter((s) => !s.hidden)
        .map((s) => {
            const data = stackedData?.get(s.key) ?? s.data
            return {
                series: s,
                value: data[dataIndex] ?? 0,
                color: s.color,
            }
        })

    // Position Y at the midpoint of all visible series values
    const yValues = seriesData.map((d) => yScale(d.value)).filter(isFinite)
    const y = yValues.length > 0 ? Math.min(...yValues) : 0

    return {
        dataIndex,
        label,
        seriesData,
        position: { x, y },
        canvasBounds,
    }
}

export function buildPointClickData(
    dataIndex: number,
    series: Series[],
    labels: string[],
    stackedData?: Map<string, number[]>
): PointClickData | null {
    if (dataIndex < 0 || dataIndex >= labels.length) {
        return null
    }

    // Find the first visible series
    const visibleSeries = series.filter((s) => !s.hidden)
    if (visibleSeries.length === 0) {
        return null
    }

    const firstSeries = visibleSeries[0]
    const firstData = stackedData?.get(firstSeries.key) ?? firstSeries.data

    return {
        seriesIndex: series.indexOf(firstSeries),
        dataIndex,
        series: firstSeries,
        value: firstData[dataIndex] ?? 0,
        label: labels[dataIndex],
        crossSeriesData: visibleSeries.map((s) => {
            const data = stackedData?.get(s.key) ?? s.data
            return { series: s, value: data[dataIndex] ?? 0 }
        }),
    }
}

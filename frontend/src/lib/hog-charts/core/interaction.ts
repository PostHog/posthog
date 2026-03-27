import { bisector } from 'd3'

import type { ChartDimensions, PointClickData, Series, TooltipContext } from './types'

/** Find the nearest data index for a given X pixel coordinate using D3 bisector (O(log n)). */
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

/** Check if a mouse position is within the plot area. */
export function isInPlotArea(mouseX: number, mouseY: number, dimensions: ChartDimensions): boolean {
    return (
        mouseX >= dimensions.plotLeft &&
        mouseX <= dimensions.plotLeft + dimensions.plotWidth &&
        mouseY >= dimensions.plotTop &&
        mouseY <= dimensions.plotTop + dimensions.plotHeight
    )
}

/** Build a TooltipContext from mouse position and data. */
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

/** Build PointClickData from a click at a data index. */
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

/** Compute linear regression (least squares) for trend line.
 * Returns [slope, intercept] or null if insufficient data. */
export function linearRegression(data: number[], endIndex?: number): { slope: number; intercept: number } | null {
    const end = endIndex ?? data.length
    if (end < 2) {
        return null
    }

    let sumX = 0
    let sumY = 0
    let sumXY = 0
    let sumX2 = 0
    let n = 0

    for (let i = 0; i < end; i++) {
        if (!isFinite(data[i])) {
            continue
        }
        sumX += i
        sumY += data[i]
        sumXY += i * data[i]
        sumX2 += i * i
        n++
    }

    if (n < 2) {
        return null
    }

    const denominator = n * sumX2 - sumX * sumX
    if (denominator === 0) {
        return null
    }

    const slope = (n * sumXY - sumX * sumY) / denominator
    const intercept = (sumY - slope * sumX) / n

    return { slope, intercept }
}

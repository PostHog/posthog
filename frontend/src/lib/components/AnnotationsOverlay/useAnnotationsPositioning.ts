import { useMemo } from 'react'

/** The chart geometry annotations are positioned against. Charts derive it from their own layout
 *  (the trends charts read quill's `useChartLayout()`), so the overlay stays library-agnostic. */
export interface AnnotationsChartGeometry {
    /** Visible x-axis ticks, as indices into `pointsX`. */
    xTicks: { value: number }[]
    /** Pixel x of every data point, index-aligned with the chart's labels. */
    pointsX: number[]
    /** Pixel x of the plot area's left edge. */
    plotLeft: number
    /** Pixel y of the plot area's bottom edge. */
    plotBottom: number
}

export interface AnnotationsPositioning {
    tickIntervalPx: number
    firstTickLeftPx: number
    /** Pixel x of a data point by index, or null if the chart isn't ready / index is out of range. */
    getDataPointX: (dataIndex: number) => number | null
}

export function useAnnotationsPositioning(geometry: AnnotationsChartGeometry): AnnotationsPositioning {
    // Calculate chart content coordinates for annotations overlay positioning
    return useMemo<AnnotationsPositioning>(() => {
        const { xTicks, pointsX } = geometry
        // NOTE: If there are lots of points on the X axis, only one tick is rendered per n data points
        // so that the axis is readable. We use that mechanism to aggregate annotations for readability
        // too. We use the data points' own pixel positions instead of just taking the graph area width,
        // because it's NOT guaranteed that the last tick is positioned at the right edge of the graph
        // area. We need to find out where it is.
        if (xTicks.length > 1 && pointsX.length > 0) {
            const tickCount = xTicks.length
            // Fall back to zero for resiliency against temporary chart inconsistencies during loading
            const firstTickLeftPx = pointsX[xTicks[0].value] ?? 0
            const lastTickLeftPx = pointsX[xTicks[tickCount - 1].value] ?? 0
            return {
                tickIntervalPx: (lastTickLeftPx - firstTickLeftPx) / (tickCount - 1),
                firstTickLeftPx,
                getDataPointX: (dataIndex: number) => pointsX[dataIndex] ?? null,
            }
        }
        return {
            tickIntervalPx: 0,
            firstTickLeftPx: 0,
            getDataPointX: () => null,
        }
    }, [geometry])
}

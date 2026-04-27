import { useMemo } from 'react'

import { Chart } from 'lib/Chart'

export interface AnnotationsPositioning {
    tickIntervalPx: number
    firstTickLeftPx: number
    /** Pixel x of a data point by index, or null if the chart isn't ready / index is out of range. */
    getDataPointX: (dataIndex: number) => number | null
}

export function useAnnotationsPositioning(
    chart: Chart | undefined,
    chartWidth: number,
    chartHeight: number
): AnnotationsPositioning {
    // Calculate chart content coordinates for annotations overlay positioning
    return useMemo<AnnotationsPositioning>(() => {
        // @ts-expect-error - _metasets is not officially exposed
        if (chart && chart.scales.x.ticks.length > 1 && chart._metasets?.[0]?.data?.length > 0) {
            const tickCount = chart.scales.x.ticks.length
            // NOTE: If there are lots of points on the X axis, Chart.js only renders a tick once n data points
            // so that the axis is readable. We use that mechanism to aggregate annotations for readability too.
            // We use the internal _metasets instead just taking graph area width, because it's NOT guaranteed that the
            // last tick is positioned at the right edge of the graph area. We need to find out where it is.
            // @ts-expect-error - _metasets is not officially exposed
            const points = chart._metasets[0].data as Point[]
            const firstTickPointIndex = chart.scales.x.ticks[0].value
            const lastTickPointIndex = chart.scales.x.ticks[tickCount - 1].value
            // Fall back to zero for resiliency against temporary chart inconsistencies during loading
            const firstTickLeftPx = points[firstTickPointIndex]?.x ?? 0
            const lastTickLeftPx = points[lastTickPointIndex]?.x ?? 0
            return {
                tickIntervalPx: (lastTickLeftPx - firstTickLeftPx) / (tickCount - 1),
                firstTickLeftPx,
                getDataPointX: (dataIndex: number) => {
                    const point = points[dataIndex]
                    return point ? point.x : null
                },
            }
        }
        return {
            tickIntervalPx: 0,
            firstTickLeftPx: 0,
            getDataPointX: () => null,
        }
    }, [chart, chartWidth, chartHeight])
}

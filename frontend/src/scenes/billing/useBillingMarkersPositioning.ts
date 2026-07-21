import { useMemo } from 'react'

import { Chart, ChartType } from 'lib/Chart'
import { Dayjs } from 'lib/dayjs'

export interface BillingMarkersPositioning {
    chartAreaLeft: number
    chartAreaTop: number
    getMarkerPosition: (date: Dayjs) => { left: number; visible: boolean }
}

// Generic over the chart type: accepting a bare `Chart` relies on Chart<'line'> widening to the
// all-types default, an assignability check tsgo resolves inconsistently across compilations.
export function useBillingMarkersPositioning<TType extends ChartType>(
    chart: Chart<TType> | undefined,
    chartWidth: number,
    chartHeight: number
): BillingMarkersPositioning {
    return useMemo<BillingMarkersPositioning>(() => {
        if (!chart || !chart.scales.x) {
            return {
                chartAreaLeft: 0,
                chartAreaTop: 0,
                getMarkerPosition: () => ({ left: 0, visible: false }),
            }
        }

        const xScale = chart.scales.x
        const yScale = chart.scales.y

        return {
            chartAreaLeft: xScale.left,
            chartAreaTop: yScale.top,
            getMarkerPosition: (date: Dayjs) => {
                // Use midnight UTC of the same day to match Chart.js annotation date string interpretation
                const utcMidnightTimestamp = date.utc().startOf('day').valueOf()
                const xPos = xScale.getPixelForValue(utcMidnightTimestamp)

                // Check if position is within visible chart area
                const visible = xPos !== undefined && xPos >= xScale.left && xPos <= xScale.right

                return {
                    left: visible ? xPos - xScale.left : 0, // Relative to chart area
                    visible,
                }
            },
        }
    }, [chart, chartWidth, chartHeight])
}

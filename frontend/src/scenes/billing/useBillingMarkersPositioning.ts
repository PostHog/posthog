import { Chart } from 'lib/Chart'
import { useMemo } from 'react'
import { Dayjs } from 'lib/dayjs'

export interface BillingMarkersPositioning {
    chartAreaLeft: number
    chartAreaTop: number
    getMarkerPosition: (date: Dayjs) => { left: number; visible: boolean }
}

export function useBillingMarkersPositioning(
    chart: Chart | undefined,
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
                const xPos = xScale.getPixelForValue(date.valueOf())

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

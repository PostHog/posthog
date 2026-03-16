import { useRef } from 'react'

import { Chart } from 'lib/Chart'

import { GraphDataset } from '~/types'

interface UseChartZoomOptions {
    datasets: GraphDataset[]
    onDateRangeZoom?: (dateFrom: string, dateTo: string) => void
    enabled: boolean
}

/**
 * Hook that encapsulates Chart.js drag-to-zoom behavior for time-series graphs.
 *
 * Returns zoom plugin options to spread into the chart config, or undefined when disabled.
 */
export function useChartZoom({
    datasets,
    onDateRangeZoom,
    enabled,
}: UseChartZoomOptions): Record<string, unknown> | undefined {
    const isResettingZoomRef = useRef(false)

    if (!enabled || !onDateRangeZoom) {
        return undefined
    }

    const resetZoom = (chart: Chart): void => {
        isResettingZoomRef.current = true
        queueMicrotask(() => {
            chart.resetZoom()
            isResettingZoomRef.current = false
        })
    }

    const getZoomDateRange = (chart: Chart): [string, string] | null => {
        const days = datasets.find((d) => !d.compare)?.days ?? datasets[0]?.days
        if (!days?.length) {
            return null
        }

        const xScale = chart.scales.x
        const minIndex = Math.max(0, Math.round(xScale.min))
        const maxIndex = Math.min(days.length - 1, Math.round(xScale.max))
        const dateFrom = days[minIndex]
        const dateTo = days[maxIndex]

        return dateFrom && dateTo ? [dateFrom, dateTo] : null
    }

    return {
        zoom: {
            drag: {
                enabled: true,
                backgroundColor: 'rgba(59, 130, 246, 0.15)',
                borderColor: 'rgba(59, 130, 246, 0.5)',
                borderWidth: 1,
            },
            mode: 'x',
            onZoomComplete: ({ chart }: { chart: Chart }) => {
                if (isResettingZoomRef.current) {
                    return
                }

                const zoomDateRange = getZoomDateRange(chart)
                if (zoomDateRange) {
                    onDateRangeZoom(...zoomDateRange)
                }

                resetZoom(chart)
            },
        },
    }
}

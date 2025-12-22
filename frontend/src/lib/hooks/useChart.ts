import { DependencyList, useEffect, useRef } from 'react'

import { Chart, ChartConfiguration, ChartType } from 'lib/Chart'

interface UseChartOptions<TType extends ChartType> {
    /** Function that builds the chart configuration. Called when deps change. */
    getConfig: () => ChartConfiguration<TType> | null
    /** Dependencies that trigger chart rebuild when changed */
    deps: DependencyList
}

interface UseChartResult<TType extends ChartType> {
    canvasRef: React.RefObject<HTMLCanvasElement>
    chartRef: React.MutableRefObject<Chart<TType> | null>
}

/**
 * Hook for safely creating and managing Chart.js instances.
 *
 * This hook encapsulates best practices for Chart.js:
 * - Guards against multiple charts on the same canvas via Chart.getChart()
 * - Properly destroys charts on cleanup and before recreation
 * - Provides typed refs for canvas and chart instance
 *
 * @example
 * ```tsx
 * const { canvasRef, chartRef } = useChart({
 *     getConfig: () => ({
 *         type: 'line',
 *         data: { labels, datasets },
 *         options: { ... }
 *     }),
 *     deps: [labels, datasets]
 * })
 *
 * return <canvas ref={canvasRef} />
 * ```
 */
export function useChart<TType extends ChartType = ChartType>({
    getConfig,
    deps,
}: UseChartOptions<TType>): UseChartResult<TType> {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const chartRef = useRef<Chart<TType> | null>(null)

    useEffect(() => {
        if (!canvasRef.current) {
            return
        }

        const config = getConfig()
        if (!config) {
            return
        }

        const ctx = canvasRef.current

        // Guard: destroy any existing chart on this canvas
        // This handles cases where React strict mode or fast refresh
        // might create multiple chart instances
        const existingChart = Chart.getChart(ctx)
        if (existingChart) {
            existingChart.destroy()
        }

        // Also destroy our ref'd chart if it exists
        // (shouldn't happen if cleanup ran, but defensive)
        if (chartRef.current) {
            chartRef.current.destroy()
            chartRef.current = null
        }

        chartRef.current = new Chart(ctx, config) as Chart<TType>

        return () => {
            // Two different charts can exist:
            // 1. orphanedChart: A chart Chart.js tracks on this canvas that we DON'T have in our ref.
            //    This happens in React StrictMode (double-mount), HMR, or if chart creation succeeded
            //    but assignment to chartRef failed. Chart.js tracks charts by canvas element internally.
            // 2. chartRef.current: The chart we explicitly created and track in our ref.
            //
            // Usually these are the same instance. But in edge cases they differ, and we must
            // destroy both to prevent memory leaks. The identity check avoids double-destroying.
            if (canvasRef.current) {
                const orphanedChart = Chart.getChart(canvasRef.current)
                if (orphanedChart && orphanedChart !== chartRef.current) {
                    orphanedChart.destroy()
                }
            }
            chartRef.current?.destroy()
            chartRef.current = null
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, deps)

    return { canvasRef, chartRef }
}

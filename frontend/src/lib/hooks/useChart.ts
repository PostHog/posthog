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

    // Keep getConfig in a ref so the effect always calls the latest version
    // without needing it (or its closed-over values) in the dependency array.
    const getConfigRef = useRef(getConfig)
    getConfigRef.current = getConfig

    // Callers pass objects/arrays/functions that get new references every render
    // (e.g. datasets, labels, callbacks). Reference-equality deps cause the
    // effect to fire every render, destroying and recreating the chart — which
    // is extremely expensive because Chart.js constructor synchronously triggers
    // bindResponsiveEvents → _resize → update → _updateDatasets.
    //
    // JSON.stringify gives value-equality semantics. Functions serialize as
    // undefined and are ignored, which is correct: function identity changes
    // don't mean chart data changed.
    const depsKey = JSON.stringify(deps)

    useEffect(() => {
        if (!canvasRef.current) {
            return
        }

        const config = getConfigRef.current()
        if (!config) {
            return
        }

        const canvas = canvasRef.current

        // Guard: destroy any existing chart on this canvas
        // This handles cases where React strict mode or fast refresh
        // might create multiple chart instances
        const existingChart = Chart.getChart(canvas)
        if (existingChart) {
            existingChart.destroy()
        }

        // Also destroy our ref'd chart if it exists
        // (shouldn't happen if cleanup ran, but defensive)
        if (chartRef.current) {
            chartRef.current.destroy()
            chartRef.current = null
        }

        chartRef.current = new Chart(canvas, config) as Chart<TType>

        return () => {
            // Two different charts can exist:
            // 1. orphanedChart: A chart Chart.js tracks on this canvas that we DON'T have in our ref.
            //    This happens in React StrictMode (double-mount), HMR, or if chart creation succeeded
            //    but assignment to chartRef failed. Chart.js tracks charts by canvas element internally.
            // 2. chartRef.current: The chart we explicitly created and track in our ref.
            //
            // Usually these are the same instance. But in edge cases they differ, and we must
            // destroy both to prevent memory leaks. The identity check avoids double-destroying.
            const orphanedChart = Chart.getChart(canvas)
            if (orphanedChart && orphanedChart !== chartRef.current) {
                orphanedChart.destroy()
            }
            chartRef.current?.destroy()
            chartRef.current = null
        }
    }, [depsKey])

    return { canvasRef, chartRef }
}

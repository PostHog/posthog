import { useLayoutEffect, useMemo, useRef } from 'react'

import { Chart, ChartConfiguration, ChartDataset } from 'lib/Chart'
import { buildTheme } from 'lib/charts/utils/theme'

import type { BenchData } from './generateBenchData'

interface ChartJsBarChartProps {
    data: BenchData
    showGrid: boolean
    /** Render bars extending horizontally (chart.js `indexAxis: 'y'`). */
    horizontal?: boolean
}

/**
 * Minimal chart.js bar chart — the engine-cost counterpart to hog-charts'
 * {@link HogChartsBarChart}. Bars are stacked to match hog-charts'
 * `TimeSeriesBarChart` default layout, and `horizontal` flips the index axis so
 * it lines up with `hog-bar-horizontal`. Bypasses LineGraph.tsx so the
 * measurement is chart.js engine cost, not adapter overhead.
 */
export function ChartJsBarChart({ data, showGrid, horizontal = false }: ChartJsBarChartProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const chartRef = useRef<Chart | null>(null)

    const theme = useMemo(() => buildTheme(), [])

    const config: ChartConfiguration<'bar'> = useMemo(() => {
        const datasets: ChartDataset<'bar'>[] = data.series.map((s, idx) => {
            const color = theme.colors[idx % theme.colors.length]
            return {
                label: s.label,
                data: s.data,
                backgroundColor: color,
                borderColor: color,
                borderWidth: 0,
            }
        })

        return {
            type: 'bar',
            data: {
                labels: data.labels,
                datasets,
            },
            options: {
                indexAxis: horizontal ? 'y' : 'x',
                animation: false,
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: true, mode: 'index', intersect: false },
                },
                interaction: { mode: 'index', intersect: false },
                scales: {
                    x: {
                        stacked: true,
                        grid: { display: showGrid, color: theme.gridColor },
                        ticks: { color: theme.axisColor, maxRotation: 0, autoSkip: true },
                    },
                    y: {
                        stacked: true,
                        grid: { display: showGrid, color: theme.gridColor },
                        ticks: { color: theme.axisColor },
                    },
                },
            },
        }
    }, [data, showGrid, horizontal, theme])

    // useLayoutEffect (not useEffect) so the chart.js construction + draw
    // completes synchronously before paint, matching the measurement window
    // used by the bench harness.
    useLayoutEffect(() => {
        if (!canvasRef.current) {
            return
        }
        chartRef.current?.destroy()
        chartRef.current = new Chart(canvasRef.current, config)
        return () => {
            chartRef.current?.destroy()
            chartRef.current = null
        }
    }, [config])

    return (
        <div className="flex-1 min-h-0 relative" data-attr="chartjs-bar-bench">
            <canvas ref={canvasRef} />
        </div>
    )
}

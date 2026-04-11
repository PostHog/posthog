import { useLayoutEffect, useMemo, useRef } from 'react'

import { Chart, ChartConfiguration, ChartDataset } from 'lib/Chart'
import { buildTheme } from 'lib/charts/utils/theme'
import { hexToRGBA } from 'lib/utils'

import type { BenchData } from './generateBenchData'

interface ChartJsLineChartProps {
    data: BenchData
    fillArea: boolean
    showGrid: boolean
}

/**
 * Minimal chart.js line chart — mirrors the feature surface of hog-charts'
 * LineChart for a fair comparison. Deliberately bypasses LineGraph.tsx (kea,
 * insights glue, custom tooltip) so the measurement is chart.js engine cost
 * vs the hog-charts engine cost, not adapter overhead.
 */
export function ChartJsLineChart({ data, fillArea, showGrid }: ChartJsLineChartProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const chartRef = useRef<Chart | null>(null)

    const theme = useMemo(() => buildTheme(), [])

    const config: ChartConfiguration<'line'> = useMemo(() => {
        const datasets: ChartDataset<'line'>[] = data.series.map((s, idx) => {
            const color = theme.colors[idx % theme.colors.length]
            return {
                label: s.label,
                data: s.data,
                borderColor: color,
                backgroundColor: fillArea ? hexToRGBA(color, 0.5) : color,
                fill: fillArea,
                pointRadius: 0,
                borderWidth: 2,
                tension: 0,
            }
        })

        return {
            type: 'line',
            data: {
                labels: data.labels,
                datasets,
            },
            options: {
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
                        grid: { display: showGrid, color: theme.gridColor },
                        ticks: { color: theme.axisColor, maxRotation: 0, autoSkip: true },
                    },
                    y: {
                        grid: { display: showGrid, color: theme.gridColor },
                        ticks: { color: theme.axisColor },
                    },
                },
            },
        }
    }, [data, fillArea, showGrid, theme])

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
        <div className="flex-1 min-h-0 relative" data-attr="chartjs-bench">
            <canvas ref={canvasRef} />
        </div>
    )
}

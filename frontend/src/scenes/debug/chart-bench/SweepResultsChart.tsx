import { useLayoutEffect, useMemo, useRef } from 'react'

import { Chart, ChartConfiguration, ChartDataset } from 'lib/Chart'
import { buildTheme } from 'lib/charts/utils/theme'

import type { ChartKind, SweepResult } from './sweepTypes'

interface SweepResultsChartProps {
    results: SweepResult[]
    metric: 'meanReadyMs' | 'meanHoverMs'
    title: string
    logY: boolean
}

/** Group sweep results into one dataset per (chart, series) combination. */
function buildDatasets(
    results: SweepResult[],
    metric: 'meanReadyMs' | 'meanHoverMs',
    colors: string[]
): { datasets: ChartDataset<'line'>[]; allPoints: number[] } {
    const groups = new Map<string, { chart: ChartKind; series: number; data: { x: number; y: number }[] }>()
    for (const r of results) {
        const key = `${r.chart}|${r.series}`
        if (!groups.has(key)) {
            groups.set(key, { chart: r.chart, series: r.series, data: [] })
        }
        groups.get(key)!.data.push({ x: r.points, y: r[metric] })
    }
    const allPointsSet = new Set<number>()
    for (const r of results) {
        allPointsSet.add(r.points)
    }
    const allPoints = Array.from(allPointsSet).sort((a, b) => a - b)

    let colorIdx = 0
    const datasets: ChartDataset<'line'>[] = []
    for (const [, group] of groups) {
        const color = colors[colorIdx % colors.length]
        colorIdx++
        group.data.sort((a, b) => a.x - b.x)
        datasets.push({
            label: `${group.chart} · ${group.series}s`,
            data: group.data,
            borderColor: color,
            backgroundColor: color,
            fill: false,
            pointRadius: 3,
            borderWidth: 2,
            tension: 0,
        })
    }
    return { datasets, allPoints }
}

export function SweepResultsChart({ results, metric, title, logY }: SweepResultsChartProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const chartRef = useRef<Chart | null>(null)
    const theme = useMemo(() => buildTheme(), [])

    const config: ChartConfiguration<'line'> = useMemo(() => {
        const { datasets } = buildDatasets(results, metric, theme.colors)
        return {
            type: 'line',
            data: { datasets },
            options: {
                animation: false,
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: true, position: 'bottom', labels: { color: theme.axisColor } },
                    tooltip: { enabled: true, mode: 'nearest', intersect: false },
                    title: { display: true, text: title, color: theme.axisColor },
                },
                interaction: { mode: 'nearest', intersect: false },
                scales: {
                    x: {
                        type: 'logarithmic',
                        title: { display: true, text: 'points', color: theme.axisColor },
                        grid: { display: true, color: theme.gridColor },
                        ticks: { color: theme.axisColor },
                    },
                    y: {
                        type: logY ? 'logarithmic' : 'linear',
                        title: { display: true, text: 'ms', color: theme.axisColor },
                        grid: { display: true, color: theme.gridColor },
                        ticks: { color: theme.axisColor },
                    },
                },
            },
        }
    }, [results, metric, title, logY, theme])

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
        <div className="flex-1 min-h-0 relative" style={{ height: 320 }}>
            <canvas ref={canvasRef} />
        </div>
    )
}

import { useEffect, useRef } from 'react'

import { Chart } from 'lib/Chart'

interface JobStatsChartProps {
    jobStats: {
        days: number
        breakdown: Record<
            string,
            {
                successful: number
                failed: number
            }
        >
    }
}

export function JobStatsChart({ jobStats }: JobStatsChartProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const chartRef = useRef<Chart | null>(null)

    useEffect(() => {
        if (!canvasRef.current || !jobStats?.breakdown) {
            return
        }

        const timestamps = Object.keys(jobStats.breakdown).sort()
        const successData = timestamps.map((ts) => jobStats.breakdown[ts].successful)
        const failedData = timestamps.map((ts) => jobStats.breakdown[ts].failed)

        const isHourly = jobStats.days === 1

        const labels = timestamps.map((ts) => {
            const d = new Date(ts)
            if (isHourly) {
                return d.toLocaleTimeString('en-US', { hour: 'numeric', hour12: true })
            }
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
        })

        if (chartRef.current) {
            chartRef.current.destroy()
        }

        const ctx = canvasRef.current.getContext('2d')
        if (!ctx) {
            return
        }

        const successColor = getComputedStyle(document.body).getPropertyValue('--success').trim() || '#388600'
        const dangerColor = getComputedStyle(document.body).getPropertyValue('--danger').trim() || '#db3707'

        chartRef.current = new Chart(ctx, {
            type: 'bar',
            data: {
                labels,
                datasets: [
                    {
                        label: 'Successful',
                        data: successData,
                        backgroundColor: successColor,
                        stack: 'stack0',
                    },
                    {
                        label: 'Failed',
                        data: failedData,
                        backgroundColor: dangerColor,
                        stack: 'stack0',
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                    },
                },
                scales: {
                    x: {
                        stacked: true,
                        grid: {
                            display: false,
                        },
                    },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        ticks: {
                            precision: 0,
                        },
                    },
                },
            },
        })

        return () => {
            if (chartRef.current) {
                chartRef.current.destroy()
            }
        }
    }, [jobStats])

    return (
        <div className="relative h-64">
            <canvas ref={canvasRef} />
        </div>
    )
}

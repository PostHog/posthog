import { useCallback, useRef } from 'react'

import { Chart, ChartConfiguration } from 'lib/Chart'

import { ChartDataPoint } from './LiveWebAnalyticsMetricsTypes'
import { TOOLTIP_STYLE, useLiveChart } from './useLiveChart'

const EmptyState = ({ message }: { message: string }): JSX.Element => (
    <div className="h-full flex items-center justify-center text-muted text-sm">{message}</div>
)

export const UsersPerMinuteChart = ({ data }: { data: ChartDataPoint[] }): JSX.Element => {
    const hasData = data.some((d) => d.users > 0)
    const dataRef = useRef<ChartDataPoint[]>(data)
    dataRef.current = data

    const createConfig = useCallback((): ChartConfiguration<'bar'> => {
        return {
            type: 'bar',
            data: {
                labels: data.map((d) => d.minute),
                datasets: [
                    {
                        label: 'New visitors',
                        data: data.map((d) => d.newUsers),
                        backgroundColor: 'rgb(34, 197, 94)',
                        borderWidth: 0,
                        borderRadius: { topLeft: 0, topRight: 0, bottomLeft: 2, bottomRight: 2 },
                        barPercentage: 0.8,
                        categoryPercentage: 0.9,
                    },
                    {
                        label: 'Returning visitors',
                        data: data.map((d) => d.returningUsers),
                        backgroundColor: 'rgb(59, 130, 246)',
                        borderWidth: 0,
                        borderRadius: { topLeft: 2, topRight: 2, bottomLeft: 0, bottomRight: 0 },
                        barPercentage: 0.8,
                        categoryPercentage: 0.9,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: {
                    duration: 300,
                    easing: 'easeOutQuart',
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                        align: 'end',
                        labels: {
                            boxWidth: 12,
                            boxHeight: 12,
                            useBorderRadius: true,
                            borderRadius: 2,
                            padding: 16,
                            font: { size: 11 },
                        },
                    },
                    tooltip: {
                        ...TOOLTIP_STYLE,
                        mode: 'index',
                        callbacks: {
                            title: (items) => {
                                const dataPoint = dataRef.current[items[0]?.dataIndex]
                                return dataPoint
                                    ? `${items[0].label} · ${dataPoint.users} visitors · ${dataPoint.pageviews} pageviews`
                                    : ''
                            },
                            label: (item) => ` ${item.dataset.label}: ${item.raw as number}`,
                        },
                    },
                },
                scales: {
                    x: {
                        stacked: true,
                        grid: { display: false },
                        ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10, font: { size: 10 } },
                    },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        grid: { color: 'rgba(0, 0, 0, 0.05)' },
                        ticks: { precision: 0, font: { size: 10 } },
                    },
                },
            },
        }
    }, [data])

    const updateData = useCallback((chart: Chart<'bar'>, newData: ChartDataPoint[]) => {
        chart.data.labels = newData.map((d) => d.minute)
        chart.data.datasets[0].data = newData.map((d) => d.newUsers)
        chart.data.datasets[1].data = newData.map((d) => d.returningUsers)
    }, [])

    const { canvasRef } = useLiveChart({ hasData, createConfig, updateData, data })

    if (!hasData) {
        return <EmptyState message="No activity in the last 30 minutes" />
    }

    return <canvas ref={canvasRef} />
}

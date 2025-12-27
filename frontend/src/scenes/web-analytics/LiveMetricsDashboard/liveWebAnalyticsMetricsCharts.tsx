import { ChartConfiguration } from 'lib/Chart'
import { getSeriesColor, getSeriesColorPalette } from 'lib/colors'
import { useChart } from 'lib/hooks/useChart'

import { ChartDataPoint, DeviceBreakdownItem } from './LiveWebAnalyticsMetricsTypes'

export const UsersPerMinuteChart = ({ data }: { data: ChartDataPoint[] }): JSX.Element => {
    const { canvasRef } = useChart<'bar'>({
        getConfig: (): ChartConfiguration<'bar'> => ({
            type: 'bar',
            data: {
                labels: data.map((d) => d.minute),
                datasets: [
                    {
                        label: 'Active users',
                        data: data.map((d) => d.users),
                        backgroundColor: getSeriesColor(0),
                        borderWidth: 0,
                        borderRadius: 2,
                        barPercentage: 0.8,
                        categoryPercentage: 0.9,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                plugins: {
                    legend: {
                        display: false,
                    },
                    tooltip: {
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        titleColor: '#fff',
                        bodyColor: '#fff',
                        padding: 12,
                        displayColors: false,
                        callbacks: {
                            title: (items) => {
                                if (items.length > 0) {
                                    return `Time: ${items[0].label}`
                                }
                                return ''
                            },
                            label: (item) => {
                                const dataPoint = data[item.dataIndex]
                                return [`Users: ${item.raw as number}`, `Pageviews: ${dataPoint?.pageviews || 0}`]
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        grid: {
                            display: false,
                        },
                        ticks: {
                            maxRotation: 0,
                            autoSkip: true,
                            maxTicksLimit: 10,
                            font: {
                                size: 10,
                            },
                        },
                    },
                    y: {
                        beginAtZero: true,
                        grid: {
                            color: 'rgba(0, 0, 0, 0.05)',
                        },
                        ticks: {
                            precision: 0,
                            font: {
                                size: 10,
                            },
                        },
                    },
                },
            },
        }),
        deps: [data],
    })

    return <canvas ref={canvasRef} />
}

export const DeviceBreakdownChart = ({ data }: { data: DeviceBreakdownItem[] }): JSX.Element => {
    const hasData = data.some((d) => d.count > 0)

    const { canvasRef } = useChart<'doughnut'>({
        getConfig: (): ChartConfiguration<'doughnut'> | null => {
            if (!hasData) {
                return null
            }

            return {
                type: 'doughnut',
                data: {
                    labels: data.map((d) => d.device),
                    datasets: [
                        {
                            data: data.map((d) => d.count),
                            backgroundColor: getSeriesColorPalette(),
                            borderColor: '#fff',
                            borderWidth: 2,
                            hoverOffset: 4,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    cutout: '60%',
                    plugins: {
                        // @ts-expect-error Types of library are out of date
                        crosshair: false,
                        legend: {
                            position: 'bottom',
                            labels: {
                                padding: 16,
                                usePointStyle: true,
                                pointStyle: 'circle',
                                font: {
                                    size: 12,
                                },
                            },
                        },
                        tooltip: {
                            backgroundColor: 'rgba(0, 0, 0, 0.8)',
                            titleColor: '#fff',
                            bodyColor: '#fff',
                            padding: 12,
                            callbacks: {
                                label: (item) => {
                                    const dataItem = data[item.dataIndex]
                                    return `${dataItem.device}: ${dataItem.count.toLocaleString()} (${dataItem.percentage.toFixed(1)}%)`
                                },
                            },
                        },
                    },
                },
            }
        },
        deps: [data, hasData],
    })

    if (!hasData) {
        return (
            <div className="h-full flex items-center justify-center text-muted text-sm">No device data available</div>
        )
    }

    return <canvas ref={canvasRef} />
}

import { useCallback, useMemo, useRef } from 'react'

import { Chart, ChartConfiguration } from 'lib/Chart'
import { getSeriesColor, getSeriesColorPalette } from 'lib/colors'

import { ChartDataPoint, DeviceBreakdownItem } from './LiveWebAnalyticsMetricsTypes'
import { TOOLTIP_STYLE, useLiveChart } from './useLiveChart'

const EmptyState = ({ message }: { message: string }): JSX.Element => (
    <div className="h-full flex items-center justify-center text-muted text-sm">{message}</div>
)

interface DeviceLegendProps {
    data: DeviceBreakdownItem[]
    colors: string[]
}

const DeviceLegend = ({ data, colors }: DeviceLegendProps): JSX.Element => (
    <div className="flex flex-row md:flex-col flex-wrap justify-center gap-x-4 gap-y-2 md:gap-2 min-w-0 overflow-hidden">
        {data.map((item, index) => (
            <div key={item.device} className="flex items-start gap-1.5 min-w-0">
                <div
                    className="w-2.5 h-2.5 md:w-3 md:h-3 rounded-full flex-shrink-0 mt-0.5"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ backgroundColor: colors[index % colors.length] }}
                />
                <div className="flex flex-col min-w-0">
                    <span className="text-xs font-medium leading-tight truncate">{item.device}</span>
                    <span className="text-xs text-muted tabular-nums leading-tight truncate">
                        {item.count.toLocaleString()} ({item.percentage.toFixed(0)}%)
                    </span>
                </div>
            </div>
        ))}
    </div>
)

interface DoughnutCenterLabelProps {
    value: number
    label: string
}

const DoughnutCenterLabel = ({ value, label }: DoughnutCenterLabelProps): JSX.Element => (
    <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="text-center">
            <div className="text-lg md:text-2xl font-bold">{value.toLocaleString()}</div>
            <div className="text-[10px] md:text-xs text-muted uppercase">{label}</div>
        </div>
    </div>
)

export const UsersPerMinuteChart = ({ data }: { data: ChartDataPoint[] }): JSX.Element => {
    const hasData = data.some((d) => d.users > 0)
    const dataRef = useRef<ChartDataPoint[]>(data)
    dataRef.current = data

    const createConfig = useCallback(
        (): ChartConfiguration<'bar'> => ({
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
                    legend: { display: false },
                    tooltip: {
                        ...TOOLTIP_STYLE,
                        displayColors: false,
                        callbacks: {
                            title: (items) => (items.length > 0 ? `Time: ${items[0].label}` : ''),
                            label: (item) => {
                                const dataPoint = dataRef.current[item.dataIndex]
                                return [`Users: ${item.raw as number}`, `Pageviews: ${dataPoint?.pageviews || 0}`]
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10, font: { size: 10 } },
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(0, 0, 0, 0.05)' },
                        ticks: { precision: 0, font: { size: 10 } },
                    },
                },
            },
        }),
        [data]
    )

    const updateData = useCallback((chart: Chart<'bar'>, newData: ChartDataPoint[]) => {
        chart.data.labels = newData.map((d) => d.minute)
        chart.data.datasets[0].data = newData.map((d) => d.users)
    }, [])

    const { canvasRef } = useLiveChart({ hasData, createConfig, updateData, data })

    if (!hasData) {
        return <EmptyState message="No activity in the last 30 minutes" />
    }

    return <canvas ref={canvasRef} />
}

interface DeviceBreakdownChartProps {
    data: DeviceBreakdownItem[]
    totalDevices: number
}

export const DeviceBreakdownChart = ({ data, totalDevices }: DeviceBreakdownChartProps): JSX.Element => {
    const hasData = data.some((d) => d.count > 0)
    const colors = useMemo(() => getSeriesColorPalette(), [])
    const dataRef = useRef<DeviceBreakdownItem[]>(data)
    dataRef.current = data

    const createConfig = useCallback(
        (): ChartConfiguration<'doughnut'> => ({
            type: 'doughnut',
            data: {
                labels: data.map((d) => d.device),
                datasets: [
                    {
                        data: data.map((d) => d.count),
                        backgroundColor: colors,
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
                    legend: { display: false },
                    tooltip: {
                        ...TOOLTIP_STYLE,
                        callbacks: {
                            label: (item) => {
                                const dataItem = dataRef.current[item.dataIndex]
                                return `${dataItem.device}: ${dataItem.count.toLocaleString()} (${dataItem.percentage.toFixed(1)}%)`
                            },
                        },
                    },
                },
            },
        }),
        [data, colors]
    )

    const updateData = useCallback((chart: Chart<'doughnut'>, newData: DeviceBreakdownItem[]) => {
        chart.data.labels = newData.map((d) => d.device)
        chart.data.datasets[0].data = newData.map((d) => d.count)
    }, [])

    const { canvasRef } = useLiveChart({ hasData, createConfig, updateData, data })

    if (!hasData) {
        return <EmptyState message="No device data available" />
    }

    return (
        <div className="flex flex-col md:flex-row h-full w-full items-center gap-4 overflow-hidden">
            <div className="relative h-32 md:h-full w-full md:flex-1 flex-shrink-0 md:min-w-0">
                <canvas ref={canvasRef} className="relative z-10" />
                <DoughnutCenterLabel value={totalDevices} label="Devices" />
            </div>
            <DeviceLegend data={data} colors={colors} />
        </div>
    )
}

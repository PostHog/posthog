import 'chartjs-adapter-dayjs-3'
import clsx from 'clsx'
import { useEffect, useRef } from 'react'

import { Chart, ChartData, ChartItem, ChartOptions, Color, GridLineOptions, TickOptions } from 'lib/Chart'
import { getGraphColors, getSeriesColor } from 'lib/colors'
import { useInsightTooltip } from 'scenes/insights/useInsightTooltip'

import { LemonTable } from '@posthog/lemon-ui'

import { InsightLabel } from 'lib/components/InsightLabel'

import { ChartSettings } from '~/queries/schema/schema-general'

import { AxisSeries, formatDataWithSettings } from '../../dataVisualizationLogic'

interface BarValueProps {
    xData: AxisSeries<string> | null
    yData: AxisSeries<number>[]
    chartSettings: ChartSettings
    presetChartHeight?: boolean
    className?: string
}

export function BarValue({ xData, yData, chartSettings, presetChartHeight, className }: BarValueProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const { getTooltip } = useInsightTooltip()
    const colors = getGraphColors()

    useEffect(() => {
        if (!xData || !yData || yData.length === 0) {
            return
        }

        // For horizontal bar charts showing total values, aggregate each series across all X points
        const labels = yData.map((series) => series.settings?.display?.label || series.column.name)
        const data = yData.map((series) => series.data.reduce((sum, val) => sum + val, 0))
        const barColors = yData.map((series, i) => series.settings?.display?.color || getSeriesColor(i))

        const chartData: ChartData = {
            labels,
            datasets: [
                {
                    data,
                    backgroundColor: barColors,
                    borderColor: barColors,
                    borderWidth: 0,
                },
            ],
        }

        const tickOptions: Partial<TickOptions> = {
            color: colors.axisLabel as Color,
            font: {
                family: '"Emoji Flags Polyfill", -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"',
                size: 12,
                weight: 'normal',
            },
        }

        const gridOptions: Partial<GridLineOptions> = {
            color: colors.axisLine as Color,
            tickColor: colors.axisLine as Color,
            tickBorderDash: [4, 2],
        }

        const options: ChartOptions<'bar'> = {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: 'y', // This makes it horizontal
            plugins: {
                crosshair: false,
                datalabels: {
                    display: false,
                },
                legend: {
                    display: false,
                },
                tooltip: {
                    enabled: false,
                    mode: 'index',
                    external: ({ tooltip }) => {
                        if (!canvasRef.current) {
                            return
                        }

                        const [tooltipRoot, tooltipEl] = getTooltip()
                        if (tooltip.opacity === 0) {
                            tooltipEl.style.opacity = '0'
                            return
                        }

                        tooltipEl.style.opacity = '1'

                        if (tooltip.body && tooltip.dataPoints && tooltip.dataPoints.length > 0) {
                            const dataPoint = tooltip.dataPoints[0]
                            const seriesIndex = dataPoint.dataIndex
                            const series = yData[seriesIndex]
                            const value = data[seriesIndex]

                            tooltipRoot.render(
                                <div className="InsightTooltip">
                                    <LemonTable
                                        dataSource={[
                                            {
                                                series: labels[seriesIndex],
                                                value: formatDataWithSettings(value, series.settings),
                                            },
                                        ]}
                                        columns={[
                                            {
                                                title: '',
                                                dataIndex: 'series',
                                                render: (value) => (
                                                    <div className="datum-label-column">
                                                        <InsightLabel
                                                            fallbackName={value?.toString()}
                                                            hideBreakdown
                                                            showSingleName
                                                            hideCompare
                                                            hideIcon
                                                            allowWrap
                                                        />
                                                    </div>
                                                ),
                                            },
                                            {
                                                title: '',
                                                dataIndex: 'value',
                                                render: (value) => <div className="series-data-cell">{value}</div>,
                                            },
                                        ]}
                                        uppercaseHeader={false}
                                        showHeader={false}
                                    />
                                </div>
                            )
                        }

                        const bounds = canvasRef.current.getBoundingClientRect()
                        tooltipEl.style.left = bounds.left + window.pageXOffset + (tooltip.caretX || 0) + 8 + 'px'
                        tooltipEl.style.top = bounds.top + window.pageYOffset + (tooltip.caretY || 0) + 8 + 'px'
                    },
                },
            },
            scales: {
                x: {
                    beginAtZero: chartSettings.leftYAxisSettings?.startAtZero ?? chartSettings.yAxisAtZero ?? true,
                    ticks: {
                        ...tickOptions,
                        display: chartSettings.leftYAxisSettings?.showTicks ?? true,
                    },
                    grid: {
                        ...gridOptions,
                        display: chartSettings.leftYAxisSettings?.showGridLines ?? true,
                    },
                    border: {
                        display: chartSettings.showXAxisBorder ?? true,
                    },
                },
                y: {
                    ticks: {
                        ...tickOptions,
                        display: chartSettings.showXAxisTicks ?? true,
                    },
                    grid: {
                        ...gridOptions,
                        drawOnChartArea: false,
                        tickLength: 12,
                        display: chartSettings.showXAxisTicks ?? true,
                    },
                    border: {
                        display: chartSettings.showYAxisBorder ?? true,
                    },
                },
            },
        }

        const newChart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
            type: 'bar',
            data: chartData,
            options,
        })

        return () => newChart.destroy()
    }, [xData, yData, chartSettings]) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div
            className={clsx(className, 'rounded bg-surface-primary relative flex flex-1 flex-col', {
                'h-[60vh]': presetChartHeight,
                'h-full': !presetChartHeight,
            })}
        >
            <div className="flex flex-1 w-full overflow-hidden h-full">
                <canvas ref={canvasRef} />
            </div>
        </div>
    )
}

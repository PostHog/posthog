import 'chartjs-adapter-dayjs-3'
import ChartDataLabels, { Context } from 'chartjs-plugin-datalabels'
import clsx from 'clsx'
import { useEffect, useRef } from 'react'

import { Chart, ChartDataset, ChartItem, ChartOptions, Plugin } from 'lib/Chart'
import { getSeriesColor } from 'lib/colors'
import { hexToRGBA } from 'lib/utils'
import { useInsightTooltip } from 'scenes/insights/useInsightTooltip'

import { LemonTable } from '@posthog/lemon-ui'

import { ChartSettings } from '~/queries/schema/schema-general'

import { AxisSeries, formatDataWithSettings } from '../../dataVisualizationLogic'

interface PieChartProps {
    xData: AxisSeries<string> | null
    yData: AxisSeries<number>[]
    chartSettings: ChartSettings
    presetChartHeight?: boolean
    className?: string
}

function getPercentageForDataPoint(context: Context): number {
    const total = context.dataset.data.reduce((a, b) => (a as number) + (b as number), 0) as number
    return ((context.dataset.data[context.dataIndex] as number) / total) * 100
}

export function PieChart({
    xData,
    yData,
    chartSettings,
    presetChartHeight,
    className,
}: PieChartProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const { getTooltip } = useInsightTooltip()

    useEffect(() => {
        if (!xData || !yData || yData.length === 0) {
            return
        }

        // For pie charts, we aggregate all Y series at each X point
        // If there's only one Y series, use X labels with Y data
        // If there are multiple Y series, use the series names as labels
        let labels: string[]
        let data: number[]
        let colors: string[]

        if (yData.length === 1) {
            // Single series: use X data as labels
            labels = xData.data
            data = yData[0].data
            colors = labels.map((_, i) => getSeriesColor(i))
        } else {
            // Multiple series: use series names as labels, sum across all X points
            labels = yData.map((series) => series.settings?.display?.label || series.column.name)
            data = yData.map((series) => series.data.reduce((sum, val) => sum + val, 0))
            colors = yData.map((series, i) => series.settings?.display?.color || getSeriesColor(i))
        }

        const datasets: ChartDataset<'pie'>[] = [
            {
                data,
                backgroundColor: colors,
                borderColor: colors,
                borderWidth: 0,
            },
        ]

        const newChart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
            type: 'pie',
            plugins: [ChartDataLabels as Plugin<'pie'>],
            data: {
                labels,
                datasets,
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                hover: {
                    mode: 'index',
                },
                layout: {
                    padding: {
                        top: 12,
                        left: 20,
                        right: 20,
                        bottom: 20,
                    },
                },
                plugins: {
                    crosshair: false,
                    datalabels: {
                        color: 'white',
                        anchor: 'end',
                        backgroundColor: (context) => {
                            return context.dataset.backgroundColor?.[context.dataIndex] || 'black'
                        },
                        display: (context) => {
                            const percentage = getPercentageForDataPoint(context)
                            return percentage > 5 ? 'auto' : false
                        },
                        padding: (context) => {
                            const value = context.dataset.data[context.dataIndex] as number
                            const paddingY = value < 10 ? 2 : 4
                            const paddingX = value < 10 ? 5 : 4
                            return { top: paddingY, bottom: paddingY, left: paddingX, right: paddingX }
                        },
                        formatter: (value: number, context) => {
                            const percentage = getPercentageForDataPoint(context)
                            return `${percentage.toFixed(1)}%`
                        },
                        font: {
                            weight: 500,
                        },
                        borderRadius: 25,
                        borderWidth: 2,
                        borderColor: 'white',
                    },
                    legend: {
                        display: chartSettings.showLegend ?? false,
                    },
                    tooltip: {
                        enabled: false,
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
                                const label = labels[dataPoint.dataIndex]
                                const value = data[dataPoint.dataIndex]
                                const total = data.reduce((sum, val) => sum + val, 0)
                                const percentage = ((value / total) * 100).toFixed(1)

                                const formattedValue =
                                    yData.length === 1
                                        ? formatDataWithSettings(value, yData[0].settings)
                                        : formatDataWithSettings(value, yData[dataPoint.dataIndex]?.settings)

                                tooltipRoot.render(
                                    <div className="InsightTooltip">
                                        <LemonTable
                                            dataSource={[
                                                {
                                                    label,
                                                    value: formattedValue,
                                                    percentage,
                                                },
                                            ]}
                                            columns={[
                                                {
                                                    title: '',
                                                    dataIndex: 'label',
                                                    render: (value) => (
                                                        <div className="datum-label-column font-semibold">{value}</div>
                                                    ),
                                                },
                                                {
                                                    title: '',
                                                    dataIndex: 'value',
                                                    render: (value, record) => (
                                                        <div className="series-data-cell">
                                                            {value} ({record.percentage}%)
                                                        </div>
                                                    ),
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
            } as ChartOptions<'pie'>,
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
            <div className="flex flex-1 w-full overflow-hidden h-full items-center justify-center">
                <canvas ref={canvasRef} />
            </div>
        </div>
    )
}

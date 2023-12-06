import 'chartjs-adapter-dayjs-3'
import './LineGraph.scss'

import { ChartData, Color, GridLineOptions, TickOptions } from 'chart.js'
import ChartDataLabels from 'chartjs-plugin-datalabels'
import clsx from 'clsx'
import { useMountedLogic, useValues } from 'kea'
import { Chart, ChartItem, ChartOptions } from 'lib/Chart'
import { getGraphColors } from 'lib/colors'
import { useEffect, useRef } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { GraphType } from '~/types'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'

export const LineGraph = (): JSX.Element => {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const { isDarkModeOn } = useValues(themeLogic)
    const colors = getGraphColors(isDarkModeOn)

    const vizLogic = useMountedLogic(dataVisualizationLogic)
    const { xData, yData, presetChartHeight } = useValues(vizLogic)

    useEffect(() => {
        if (!xData || !yData) {
            return
        }

        const data: ChartData = {
            labels: xData,
            datasets: yData.map((n) => ({
                label: 'Dataset 1',
                data: n,
                borderColor: 'red',
            })),
        }

        const tickOptions: Partial<TickOptions> = {
            color: colors.axisLabel as Color,
            font: {
                family: '-apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"',
                size: 12,
                weight: '500',
            },
        }

        const gridOptions: Partial<GridLineOptions> = {
            color: colors.axisLine as Color,
            borderColor: colors.axisLine as Color,
            tickColor: colors.axisLine as Color,
            borderDash: [4, 2],
        }

        const options: ChartOptions = {
            responsive: true,
            maintainAspectRatio: false,
            elements: {
                line: {
                    tension: 0,
                },
            },
            plugins: {
                datalabels: {
                    color: 'white',
                    anchor: (context) => {
                        const datum = context.dataset.data[context.dataIndex]
                        return typeof datum !== 'number' ? 'end' : datum > 0 ? 'end' : 'start'
                    },
                    backgroundColor: (context) => {
                        return (context.dataset.borderColor as string) || 'black'
                    },
                    display: () => {
                        return true
                    },
                    borderWidth: 2,
                    borderRadius: 4,
                    borderColor: 'white',
                },
                legend: {
                    display: false,
                },
                // @ts-expect-error Types of library are out of date
                crosshair: {
                    snap: {
                        enabled: true, // Snap crosshair to data points
                    },
                    sync: {
                        enabled: false, // Sync crosshairs across multiple Chartjs instances
                    },
                    zoom: {
                        enabled: false, // Allow drag to zoom
                    },
                    line: {
                        color: colors.crosshair ?? undefined,
                        width: 1,
                    },
                },
            },
            hover: {
                mode: 'nearest',
                axis: 'x',
                intersect: false,
            },
            scales: {
                x: {
                    display: true,
                    beginAtZero: true,
                    ticks: tickOptions,
                    grid: {
                        ...gridOptions,
                        drawOnChartArea: false,
                        tickLength: 12,
                    },
                },
                y: {
                    display: true,
                    beginAtZero: true,
                    stacked: false,
                    ticks: {
                        display: true,
                        ...tickOptions,
                        precision: 1,
                    },
                    grid: gridOptions,
                },
            },
        }

        const newChart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
            type: GraphType.Line,
            data,
            options,
            plugins: [ChartDataLabels],
        })
        return () => newChart.destroy()
    }, [xData, yData])

    return (
        <div
            className={clsx('rounded bg-bg-light relative flex flex-1 flex-col p-2', {
                DataVisualization__LineGraph: presetChartHeight,
            })}
        >
            <div className="flex flex-1 w-full h-full overflow-hidden">
                <canvas ref={canvasRef} />
            </div>
        </div>
    )
}

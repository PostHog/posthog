import 'chartjs-adapter-dayjs-3'
import './LineGraph.scss'
// TODO: Move the below scss to somewhere more common
import '../../../../../scenes/insights/InsightTooltip/InsightTooltip.scss'

import { LemonTable } from '@posthog/lemon-ui'
import { ChartData, ChartType, Color, GridLineOptions, TickOptions, TooltipModel } from 'chart.js'
import annotationPlugin, { AnnotationPluginOptions, LineAnnotationOptions } from 'chartjs-plugin-annotation'
import ChartDataLabels from 'chartjs-plugin-datalabels'
import clsx from 'clsx'
import { useValues } from 'kea'
import { Chart, ChartItem, ChartOptions } from 'lib/Chart'
import { getGraphColors, getSeriesColor } from 'lib/colors'
import { InsightLabel } from 'lib/components/InsightLabel'
import { useEffect, useRef } from 'react'
import { ensureTooltip } from 'scenes/insights/views/LineGraph/LineGraph'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { ChartDisplayType, GraphType } from '~/types'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { displayLogic } from '../../displayLogic'

export const LineGraph = (): JSX.Element => {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const { isDarkModeOn } = useValues(themeLogic)
    const colors = getGraphColors(isDarkModeOn)

    // TODO: Extract this logic out of this component and inject values in
    // via props. Make this a purely presentational component
    const { xData, yData, presetChartHeight, visualizationType } = useValues(dataVisualizationLogic)
    const isBarChart = visualizationType === ChartDisplayType.ActionsBar

    const { goalLines } = useValues(displayLogic)

    useEffect(() => {
        if (!xData || !yData) {
            return
        }

        const data: ChartData = {
            labels: xData.data,
            datasets: yData.map(({ data }, index) => {
                const color = getSeriesColor(index)

                return {
                    data,
                    borderColor: color,
                    backgroundColor: color,
                    borderWidth: isBarChart ? 0 : 2,
                    pointRadius: 0,
                    hitRadius: 0,
                    order: 1,
                    hoverBorderWidth: isBarChart ? 0 : 2,
                    hoverBorderRadius: isBarChart ? 0 : 2,
                    type: isBarChart ? GraphType.Bar : GraphType.Line,
                } as ChartData['datasets'][0]
            }),
        }

        const annotations = goalLines.reduce(
            (acc, cur, curIndex) => {
                const line: LineAnnotationOptions = {
                    label: {
                        display: true,
                        content: cur.label,
                        position: 'end',
                    },
                    scaleID: 'y',
                    value: cur.value,
                }

                acc.annotations[`line${curIndex}`] = {
                    type: 'line',
                    ...line,
                }

                return acc
            },
            { annotations: {} } as AnnotationPluginOptions
        )

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
                        // TODO: Update when "show values on chart" becomes an option
                        return false
                    },
                    borderWidth: 2,
                    borderRadius: 4,
                    borderColor: 'white',
                },
                legend: {
                    display: false,
                },
                annotation: annotations,
                ...(isBarChart
                    ? { crosshair: false }
                    : {
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
                      }),
                // TODO: A lot of this is v similar to the trends LineGraph - considering merging these
                tooltip: {
                    enabled: false,
                    mode: 'nearest',
                    intersect: false,
                    external({ tooltip }: { chart: Chart; tooltip: TooltipModel<ChartType> }) {
                        if (!canvasRef.current) {
                            return
                        }

                        const [tooltipRoot, tooltipEl] = ensureTooltip()
                        if (tooltip.opacity === 0) {
                            tooltipEl.style.opacity = '0'
                            return
                        }

                        // Set caret position
                        // Reference: https://www.chartjs.org/docs/master/configuration/tooltip.html
                        tooltipEl.classList.remove('above', 'below', 'no-transform')
                        tooltipEl.classList.add(tooltip.yAlign || 'no-transform')
                        tooltipEl.style.opacity = '1'

                        if (tooltip.body) {
                            const referenceDataPoint = tooltip.dataPoints[0] // Use this point as reference to get the date
                            tooltipRoot.render(
                                <div className="InsightTooltip">
                                    <LemonTable
                                        dataSource={yData.map(({ data, column }) => ({
                                            series: column.name,
                                            data: data[referenceDataPoint.dataIndex],
                                        }))}
                                        columns={[
                                            {
                                                title: xData.data[referenceDataPoint.dataIndex],
                                                dataIndex: 'series',
                                                render: (value) => {
                                                    return (
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
                                                    )
                                                },
                                            },
                                            {
                                                title: '',
                                                dataIndex: 'data',
                                                render: (value) => {
                                                    return <div className="series-data-cell">{value}</div>
                                                },
                                            },
                                        ]}
                                        size="small"
                                        uppercaseHeader={false}
                                        rowRibbonColor={(_datum, index) => getSeriesColor(index)}
                                        showHeader
                                    />
                                </div>
                            )
                        }

                        const bounds = canvasRef.current.getBoundingClientRect()
                        const horizontalBarTopOffset = 0 // TODO: Change this when horizontal bar charts are a thing
                        const tooltipClientTop = bounds.top + window.pageYOffset + horizontalBarTopOffset

                        const chartClientLeft = bounds.left + window.pageXOffset
                        const defaultOffsetLeft = Math.max(chartClientLeft, chartClientLeft + tooltip.caretX + 8)
                        const maxXPosition = bounds.right - tooltipEl.clientWidth
                        const tooltipClientLeft =
                            defaultOffsetLeft > maxXPosition
                                ? chartClientLeft + tooltip.caretX - tooltipEl.clientWidth - 8 // If tooltip is too large (or close to the edge), show it to the left of the data point instead
                                : defaultOffsetLeft

                        tooltipEl.style.top = tooltipClientTop + 'px'
                        tooltipEl.style.left = tooltipClientLeft + 'px'
                    },
                },
            },
            hover: {
                mode: isBarChart ? 'point' : 'nearest',
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

        Chart.register(annotationPlugin)
        const newChart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
            type: isBarChart ? GraphType.Bar : GraphType.Line,
            data,
            options,
            plugins: [ChartDataLabels],
        })
        return () => newChart.destroy()
    }, [xData, yData, visualizationType, goalLines])

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

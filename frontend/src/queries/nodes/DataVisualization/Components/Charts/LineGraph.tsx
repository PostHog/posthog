import 'chartjs-adapter-dayjs-3'
import './LineGraph.scss'
// TODO: Move the below scss to somewhere more common
import '../../../../../scenes/insights/InsightTooltip/InsightTooltip.scss'

import { LemonTable } from '@posthog/lemon-ui'
import {
    ChartData,
    ChartType,
    ChartTypeRegistry,
    Color,
    GridLineOptions,
    ScaleOptionsByType,
    TickOptions,
    TooltipModel,
} from 'chart.js'
import annotationPlugin, { AnnotationPluginOptions, LineAnnotationOptions } from 'chartjs-plugin-annotation'
import dataLabelsPlugin from 'chartjs-plugin-datalabels'
import ChartjsPluginStacked100 from 'chartjs-plugin-stacked100'
import chartTrendline from 'chartjs-plugin-trendline'
import clsx from 'clsx'
import { useValues } from 'kea'
import { Chart, ChartItem, ChartOptions } from 'lib/Chart'
import { getGraphColors, getSeriesColor } from 'lib/colors'
import { InsightLabel } from 'lib/components/InsightLabel'
import { hexToRGBA } from 'lib/utils'
import { useEffect, useRef } from 'react'
import { ensureTooltip } from 'scenes/insights/views/LineGraph/LineGraph'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { ChartSettings, YAxisSettings } from '~/queries/schema'
import { ChartDisplayType, GraphType } from '~/types'

import { AxisSeriesSettings, dataVisualizationLogic, formatDataWithSettings } from '../../dataVisualizationLogic'
import { displayLogic } from '../../displayLogic'

Chart.register(annotationPlugin)
Chart.register(ChartjsPluginStacked100)
Chart.register(chartTrendline)

const getGraphType = (chartType: ChartDisplayType, settings: AxisSeriesSettings | undefined): GraphType => {
    if (!settings || !settings.display || settings.display?.displayType === 'auto') {
        return chartType === ChartDisplayType.ActionsBar || chartType === ChartDisplayType.ActionsStackedBar
            ? GraphType.Bar
            : GraphType.Line
    }

    if (settings.display?.displayType === 'bar') {
        return GraphType.Bar
    }

    return GraphType.Line
}

const getYAxisSettings = (
    chartSettings: ChartSettings,
    settings: YAxisSettings | undefined,
    stacked: boolean,
    position: 'left' | 'right',
    tickOptions: Partial<TickOptions>,
    gridOptions: Partial<GridLineOptions>
): ScaleOptionsByType<ChartTypeRegistry['line']['scales']> => {
    if (settings?.scale === 'logarithmic') {
        // @ts-expect-error - needless complaining from chart.js types
        return {
            display: true,
            stacked: stacked,
            type: 'logarithmic',
            grid: gridOptions,
            position,
        }
    }

    return {
        display: true,
        beginAtZero: settings?.startAtZero ?? chartSettings.yAxisAtZero ?? true,
        stacked: stacked,
        type: 'linear',
        // @ts-expect-error - needless complaining from chart.js types
        ticks: {
            display: true,
            ...tickOptions,
            precision: 1,
        },
        grid: gridOptions,
        position,
    }
}

export const LineGraph = (): JSX.Element => {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const { isDarkModeOn } = useValues(themeLogic)
    const colors = getGraphColors(isDarkModeOn)

    // TODO: Extract this logic out of this component and inject values in
    // via props. Make this a purely presentational component
    const { xData, yData, presetChartHeight, visualizationType, showEditingUI, chartSettings } =
        useValues(dataVisualizationLogic)
    const isBarChart =
        visualizationType === ChartDisplayType.ActionsBar || visualizationType === ChartDisplayType.ActionsStackedBar
    const isStackedBarChart = visualizationType === ChartDisplayType.ActionsStackedBar
    const isAreaChart = visualizationType === ChartDisplayType.ActionsAreaGraph

    const { goalLines } = useValues(displayLogic)

    useEffect(() => {
        if (!xData || !yData) {
            return
        }

        const hasRightYAxis = !!yData.find((n) => n.settings?.display?.yAxisPosition === 'right')
        const hasLeftYAxis = !hasRightYAxis || !!yData.find((n) => n.settings?.display?.yAxisPosition === 'left')

        const data: ChartData = {
            labels: xData.data,
            datasets: yData.map(({ data, settings }, index) => {
                const color = getSeriesColor(index)
                const backgroundColor = isAreaChart ? hexToRGBA(color, 0.5) : color

                const graphType = getGraphType(visualizationType, settings)

                return {
                    data,
                    borderColor: color,
                    backgroundColor: backgroundColor,
                    borderWidth: graphType === GraphType.Bar ? 0 : 2,
                    pointRadius: 0,
                    hitRadius: 0,
                    order: 1,
                    hoverBorderWidth: graphType === GraphType.Bar ? 0 : 2,
                    hoverBorderRadius: graphType === GraphType.Bar ? 0 : 2,
                    type: graphType,
                    fill: isAreaChart ? 'origin' : false,
                    yAxisID: settings?.display?.yAxisPosition === 'right' ? 'yRight' : 'yLeft',
                    ...(settings?.display?.trendLine
                        ? {
                              trendlineLinear: {
                                  colorMin: hexToRGBA(color, 0.6),
                                  colorMax: hexToRGBA(color, 0.6),
                                  lineStyle: 'dotted',
                                  width: 3,
                              },
                          }
                        : {}),
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
                    scaleID: hasLeftYAxis ? 'yLeft' : 'yRight',
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
                weight: 'normal',
            },
        }

        const gridOptions: Partial<GridLineOptions> = {
            color: colors.axisLine as Color,
            tickColor: colors.axisLine as Color,
            tickBorderDash: [4, 2],
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
                stacked100: { enable: isStackedBarChart && chartSettings.stackBars100, precision: 1 },
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
                    formatter: () => {
                        // TODO: Update when "show values on chart" becomes an option
                        // const data = context.chart.data as ExtendedChartData
                        // const { datasetIndex, dataIndex } = context
                        // const percentageValue = data.calculatedData?.[datasetIndex][dataIndex]
                        // if (isStackedBarChart && chartSettings.stackBars100) {
                        //     value = Number(percentageValue)
                        //     return percentage(value / 100)
                        // }
                        // return value
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
                    mode: 'index',
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
                                        dataSource={yData.map(({ data, column, settings }) => ({
                                            series: settings?.display?.label || column.name,
                                            data: formatDataWithSettings(data[referenceDataPoint.dataIndex], settings),
                                            rawData: data[referenceDataPoint.dataIndex],
                                            dataIndex: referenceDataPoint.dataIndex,
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
                                                render: (value, record) => {
                                                    if (isStackedBarChart && chartSettings.stackBars100) {
                                                        const total = yData
                                                            .map((n) => n.data[record.dataIndex])
                                                            .reduce((acc, cur) => acc + cur, 0)
                                                        const percentageLabel: number = parseFloat(
                                                            ((record.rawData / total) * 100).toFixed(1)
                                                        )

                                                        return (
                                                            <div className="series-data-cell">
                                                                {value} ({percentageLabel}%)
                                                            </div>
                                                        )
                                                    }

                                                    return <div className="series-data-cell">{value}</div>
                                                },
                                            },
                                        ]}
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
                    stacked: isStackedBarChart,
                    ticks: tickOptions,
                    grid: {
                        ...gridOptions,
                        drawOnChartArea: false,
                        tickLength: 12,
                    },
                },
                ...(hasLeftYAxis
                    ? {
                          yLeft: getYAxisSettings(
                              chartSettings,
                              chartSettings.leftYAxisSettings,
                              isAreaChart || isStackedBarChart,
                              'left',
                              tickOptions,
                              gridOptions
                          ),
                      }
                    : {}),
                ...(hasRightYAxis
                    ? {
                          yRight: getYAxisSettings(
                              chartSettings,
                              chartSettings.rightYAxisSettings,
                              isAreaChart || isStackedBarChart,
                              'right',
                              tickOptions,
                              gridOptions
                          ),
                      }
                    : {}),
            },
        }

        const newChart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
            type: isBarChart ? GraphType.Bar : GraphType.Line,
            data,
            options,
            plugins: [dataLabelsPlugin],
        })
        return () => newChart.destroy()
    }, [xData, yData, visualizationType, goalLines, chartSettings])

    return (
        <div
            className={clsx('rounded bg-bg-light relative flex flex-1 flex-col p-2', {
                DataVisualization__LineGraph: presetChartHeight,
                'h-full': !presetChartHeight,
                border: showEditingUI,
            })}
        >
            <div className="flex flex-1 w-full h-full overflow-hidden">
                <canvas ref={canvasRef} />
            </div>
        </div>
    )
}

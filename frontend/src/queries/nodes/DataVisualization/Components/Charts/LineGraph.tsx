// TODO: Move the below scss to somewhere more common
import '../../../../../scenes/insights/InsightTooltip/InsightTooltip.scss'

import 'chartjs-adapter-dayjs-3'
import annotationPlugin, { AnnotationPluginOptions, LineAnnotationOptions } from 'chartjs-plugin-annotation'
import dataLabelsPlugin from 'chartjs-plugin-datalabels'
import ChartjsPluginStacked100 from 'chartjs-plugin-stacked100'
import chartTrendline from 'chartjs-plugin-trendline'
import clsx from 'clsx'

import { LemonTable, lemonToast } from '@posthog/lemon-ui'

import {
    Chart,
    ChartData,
    ChartOptions,
    ChartType,
    ChartTypeRegistry,
    Color,
    GridLineOptions,
    ScaleOptionsByType,
    TickOptions,
    TooltipModel,
} from 'lib/Chart'
import { getGraphColors, getSeriesColor } from 'lib/colors'
import { InsightLabel } from 'lib/components/InsightLabel'
import { useChart } from 'lib/hooks/useChart'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { hexToRGBA } from 'lib/utils'
import { useInsightTooltip } from 'scenes/insights/useInsightTooltip'

import { ChartSettings, GoalLine, YAxisSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType, GraphType } from '~/types'

import { AxisSeries, AxisSeriesSettings, formatDataWithSettings } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'

Chart.register(annotationPlugin)
Chart.register(ChartjsPluginStacked100)
Chart.register(chartTrendline)

const getGraphType = (chartType: ChartDisplayType, settings: AxisSeriesSettings | undefined): GraphType => {
    if (!settings || !settings.display || !settings.display.displayType || settings.display?.displayType === 'auto') {
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
    const mixedGridOptions = {
        ...gridOptions,
        display: settings?.showGridLines ?? true,
    }

    const commonOptions = {
        display: true,
        stacked: stacked,
        grid: mixedGridOptions,
        position,
        border: {
            display: chartSettings.showYAxisBorder ?? true,
        },
    }

    if (settings?.scale === 'logarithmic') {
        // @ts-expect-error - needless complaining from chart.js types
        return {
            ...commonOptions,
            type: 'logarithmic',
        }
    }

    return {
        ...commonOptions,
        beginAtZero: settings?.startAtZero ?? chartSettings.yAxisAtZero ?? true,
        type: 'linear',
        // @ts-expect-error - needless complaining from chart.js types
        ticks: {
            display: settings?.showTicks ?? true,
            ...tickOptions,
            precision: 1,
        },
    }
}

export type LineGraphProps = {
    xData: AxisSeries<string> | null
    yData: AxisSeries<number>[] | AxisBreakdownSeries<number>[]
    visualizationType: ChartDisplayType
    chartSettings: ChartSettings
    presetChartHeight?: boolean
    dashboardId?: string
    goalLines?: GoalLine[]
    className?: string
}

// LineGraph displays a graph using either x and y data or series breakdown data
export const LineGraph = ({
    xData,
    yData,
    presetChartHeight,
    visualizationType,
    chartSettings,
    dashboardId,
    goalLines = [],
    className,
}: LineGraphProps): JSX.Element => {
    const { getTooltip } = useInsightTooltip()
    const { ref: containerRef, height } = useResizeObserver()

    const isBarChart =
        visualizationType === ChartDisplayType.ActionsBar || visualizationType === ChartDisplayType.ActionsStackedBar
    const isStackedBarChart = visualizationType === ChartDisplayType.ActionsStackedBar
    const isAreaChart = visualizationType === ChartDisplayType.ActionsAreaGraph

    const { canvasRef } = useChart({
        getConfig: () => {
            const colors = getGraphColors()

            let ySeriesData: AxisSeries<number>[] | AxisBreakdownSeries<number>[]
            let xSeriesData: AxisSeries<string>
            let hasRightYAxis = false
            let hasLeftYAxis = false
            if (xData && yData) {
                ySeriesData = yData
                xSeriesData = xData
                hasRightYAxis = !!ySeriesData.find((n) => n.settings?.display?.yAxisPosition === 'right')
                hasLeftYAxis =
                    !chartSettings.stackBars100 &&
                    (!hasRightYAxis || !!ySeriesData.find((n) => n.settings?.display?.yAxisPosition === 'left'))
            } else {
                return null
            }

            const MAX_SERIES = 200
            if (ySeriesData.length > MAX_SERIES) {
                if (!dashboardId) {
                    lemonToast.warning(
                        `This breakdown has too many series (${ySeriesData.length}). Only showing top ${MAX_SERIES} series in the chart. All series are still available in the table below.`
                    )
                }
                ySeriesData = ySeriesData.slice(0, MAX_SERIES)
            }

            const data: ChartData = {
                labels: xSeriesData.data,
                datasets: ySeriesData.map(({ data: seriesData, settings, ...rest }, index) => {
                    const seriesColor = settings?.display?.color ?? getSeriesColor(index)
                    const backgroundColor = isAreaChart ? hexToRGBA(seriesColor, 0.5) : seriesColor

                    const graphType = getGraphType(visualizationType, settings)

                    let yAxisID = 'yLeft'
                    if (chartSettings.stackBars100) {
                        yAxisID = 'y'
                    } else if (settings?.display?.yAxisPosition === 'right') {
                        yAxisID = 'yRight'
                    }

                    const getLabel = (): string => {
                        if ('name' in rest) {
                            return rest.name
                        }

                        return rest.column.name
                    }

                    return {
                        data: seriesData,
                        label: getLabel(),
                        borderColor: seriesColor,
                        backgroundColor: backgroundColor,
                        borderWidth: graphType === GraphType.Bar ? 0 : 2,
                        pointRadius: 0,
                        hitRadius: 0,
                        order: 1,
                        hoverBorderWidth: graphType === GraphType.Bar ? 0 : 2,
                        hoverBorderRadius: graphType === GraphType.Bar ? 0 : 2,
                        type: graphType,
                        fill: isAreaChart ? 'origin' : false,
                        yAxisID,
                        ...(settings?.display?.trendLine &&
                        xData &&
                        yData &&
                        xData.data.length > 0 &&
                        seriesData.length > 0
                            ? {
                                  trendlineLinear: {
                                      colorMin: hexToRGBA(seriesColor, 0.6),
                                      colorMax: hexToRGBA(seriesColor, 0.6),
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
                            display: cur.displayLabel ?? true,
                            content: cur.label,
                            position: cur.position ?? 'end',
                        },
                        scaleID: hasLeftYAxis ? 'yLeft' : 'yRight',
                        value: cur.value,
                        enter: (ctx) => {
                            if (ctx.chart.options.plugins?.annotation?.annotations) {
                                const annotationsList = ctx.chart.options.plugins.annotation.annotations as Record<
                                    string,
                                    any
                                >
                                if (annotationsList[`line${curIndex}`]) {
                                    annotationsList[`line${curIndex}`].label.content = `${
                                        cur.label
                                    }: ${cur.value.toLocaleString()}`
                                    const tooltipEl = document.getElementById('InsightTooltipWrapper')

                                    if (tooltipEl) {
                                        tooltipEl.style.display = 'none'
                                    }

                                    ctx.chart.update()
                                }
                            }
                        },
                        leave: (ctx) => {
                            if (ctx.chart.options.plugins?.annotation?.annotations) {
                                const annotationsList = ctx.chart.options.plugins.annotation.annotations as Record<
                                    string,
                                    any
                                >
                                if (annotationsList[`line${curIndex}`]) {
                                    annotationsList[`line${curIndex}`].label.content = cur.label

                                    const tooltipEl = document.getElementById('InsightTooltipWrapper')
                                    if (tooltipEl) {
                                        tooltipEl.style.display = 'block'
                                    }

                                    ctx.chart.update()
                                }
                            }
                        },
                    }

                    acc.annotations[`line${curIndex}`] = {
                        type: 'line' as const,
                        ...line,
                    }

                    return acc
                },
                { annotations: {} } as AnnotationPluginOptions
            )

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
                            return false
                        },
                        formatter: () => {},
                        borderWidth: 2,
                        borderRadius: 4,
                        borderColor: 'white',
                    },
                    legend: {
                        display: chartSettings.showLegend ?? false,
                    },
                    annotation: annotations,
                    ...(isBarChart
                        ? { crosshair: false }
                        : {
                              crosshair: {
                                  snap: {
                                      enabled: true,
                                  },
                                  sync: {
                                      enabled: false,
                                  },
                                  zoom: {
                                      enabled: false,
                                  },
                                  line: {
                                      color: colors.crosshair ?? undefined,
                                      width: 1,
                                  },
                              },
                          }),
                    tooltip: {
                        enabled: false,
                        mode: 'index',
                        intersect: false,
                        external({ chart, tooltip }: { chart: Chart; tooltip: TooltipModel<ChartType> }) {
                            const canvas = chart.canvas
                            if (!canvas) {
                                return
                            }

                            const [tooltipRoot, tooltipEl] = getTooltip()
                            if (tooltip.opacity === 0) {
                                tooltipEl.style.opacity = '0'
                                return
                            }

                            tooltipEl.classList.remove('above', 'below', 'no-transform')
                            tooltipEl.classList.add(tooltip.yAlign || 'no-transform')
                            tooltipEl.style.opacity = '1'

                            if (tooltip.body) {
                                const referenceDataPoint = tooltip.dataPoints[0]

                                const tooltipData = ySeriesData.map((series) => {
                                    const seriesName =
                                        series?.settings?.display?.label ||
                                        ('column' in series ? series.column.name : series.name)
                                    return {
                                        series: seriesName,
                                        data: formatDataWithSettings(
                                            series.data[referenceDataPoint.dataIndex],
                                            series.settings
                                        ),
                                        rawData: series.data[referenceDataPoint.dataIndex],
                                        dataIndex: referenceDataPoint.dataIndex,
                                        isTotalRow: false,
                                    }
                                })

                                const tooltipTotalData = ySeriesData.filter(
                                    (n) => n.settings?.formatting?.style !== 'percent'
                                )

                                if (tooltipTotalData.length > 1 && chartSettings.showTotalRow !== false) {
                                    const totalRawData = tooltipTotalData.reduce((acc, cur) => {
                                        acc += cur.data[referenceDataPoint.dataIndex]
                                        return acc
                                    }, 0)

                                    tooltipData.push({
                                        series: '',
                                        data: totalRawData.toLocaleString(),
                                        rawData: totalRawData,
                                        dataIndex: referenceDataPoint.dataIndex,
                                        isTotalRow: true,
                                    })
                                }

                                tooltipRoot.render(
                                    <div className="InsightTooltip">
                                        <LemonTable
                                            dataSource={tooltipData}
                                            columns={[
                                                {
                                                    title: xSeriesData.data[referenceDataPoint.dataIndex],
                                                    dataIndex: 'series',
                                                    render: (value, record) => {
                                                        if (record.isTotalRow) {
                                                            return (
                                                                <div className="datum-label-column font-extrabold">
                                                                    Total
                                                                </div>
                                                            )
                                                        }

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
                                                            const total = ySeriesData
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
                                            rowRibbonColor={(_datum, index) => {
                                                if (_datum.isTotalRow) {
                                                    return undefined
                                                }

                                                return (
                                                    ySeriesData[index]?.settings?.display?.color ??
                                                    getSeriesColor(index)
                                                )
                                            }}
                                            showHeader
                                        />
                                    </div>
                                )
                            }

                            const bounds = canvas.getBoundingClientRect()
                            const horizontalBarTopOffset = 0
                            const tooltipClientTop = bounds.top + window.pageYOffset + horizontalBarTopOffset

                            const chartClientLeft = bounds.left + window.pageXOffset
                            const defaultOffsetLeft = Math.max(chartClientLeft, chartClientLeft + tooltip.caretX + 8)
                            const maxXPosition = bounds.right - tooltipEl.clientWidth
                            const tooltipClientLeft =
                                defaultOffsetLeft > maxXPosition
                                    ? chartClientLeft + tooltip.caretX - tooltipEl.clientWidth - 8
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
                            display: chartSettings.showXAxisBorder ?? true,
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

            return {
                type: isBarChart ? GraphType.Bar : GraphType.Line,
                data,
                options,
                plugins: [dataLabelsPlugin],
            }
        },
        deps: [xData, yData, visualizationType, goalLines, chartSettings, dashboardId, getTooltip],
    })

    return (
        <div
            className={clsx(className, 'rounded bg-surface-primary relative flex flex-1 flex-col', {
                'h-[60vh]': presetChartHeight,
                'h-full': !presetChartHeight,
            })}
            ref={containerRef}
        >
            <div
                className={clsx('flex flex-1 w-full overflow-hidden', {
                    'h-full': !presetChartHeight,
                })}
                // eslint-disable-next-line react/forbid-dom-props
                style={height ? { height: `${height}px` } : {}}
            >
                <canvas ref={canvasRef} />
            </div>
        </div>
    )
}

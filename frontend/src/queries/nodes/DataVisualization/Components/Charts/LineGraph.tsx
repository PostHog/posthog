// TODO: Move the below scss to somewhere more common
import '../../../../../scenes/insights/InsightTooltip/InsightTooltip.scss'

import 'chartjs-adapter-dayjs-3'

import annotationPlugin, { AnnotationPluginOptions, LineAnnotationOptions } from 'chartjs-plugin-annotation'
import dataLabelsPlugin from 'chartjs-plugin-datalabels'
import ChartjsPluginStacked100 from 'chartjs-plugin-stacked100'
import chartTrendline from 'chartjs-plugin-trendline'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonTable, lemonToast } from '@posthog/lemon-ui'

import {
    ActiveElement,
    Chart,
    ChartData,
    ChartEvent,
    ChartOptions,
    ChartType,
    ChartTypeRegistry,
    Color,
    GridLineOptions,
    ScaleOptionsByType,
    TickOptions,
    TooltipModel,
} from 'lib/Chart'
import { resolveVariableColor } from 'lib/charts/utils/color'
import { createXAxisTickCallback } from 'lib/charts/utils/dates'
import { getGraphColors, getSeriesColor } from 'lib/colors'
import { InsightLabel } from 'lib/components/InsightLabel'
import { useChart } from 'lib/hooks/useChart'
import { useKeyHeld } from 'lib/hooks/useKeyHeld'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { hexToRGBA, uuid } from 'lib/utils'
import { useInsightTooltip } from 'scenes/insights/useInsightTooltip'
import { teamLogic } from 'scenes/teamLogic'

import { ChartSettings, GoalLine, YAxisSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType, GraphType } from '~/types'

import { AxisSeries, AxisSeriesSettings, formatDataWithSettings } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { lineGraphLogic } from './lineGraphLogic'

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
    yData: AxisSeries<number | null>[] | AxisBreakdownSeries<number>[]
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
    const { tooltipId, getTooltip, showTooltip, hideTooltip, positionTooltip } = useInsightTooltip()
    const { ref: containerRef, height } = useResizeObserver()

    const logicKey = useMemo(() => uuid(), [])
    const { hoveredDatasetIndex } = useValues(lineGraphLogic({ key: logicKey }))
    const { setHoveredDatasetIndex } = useActions(lineGraphLogic({ key: logicKey }))
    const { timezone } = useValues(teamLogic)
    const isShiftPressed = useKeyHeld('Shift')

    useEffect(() => {
        if (!isShiftPressed) {
            setHoveredDatasetIndex(null)
        }
    }, [isShiftPressed, setHoveredDatasetIndex])

    const isBarChart =
        visualizationType === ChartDisplayType.ActionsBar || visualizationType === ChartDisplayType.ActionsStackedBar
    const isStackedBarChart = visualizationType === ChartDisplayType.ActionsStackedBar
    const isAreaChart = visualizationType === ChartDisplayType.ActionsAreaGraph
    const isHighlightBarMode = isBarChart && isStackedBarChart && isShiftPressed

    const MAX_SERIES = 200
    const ySeriesData = useMemo(() => {
        if (!yData) {
            return null
        }
        if (yData.length > MAX_SERIES) {
            if (!dashboardId) {
                lemonToast.warning(
                    `This breakdown has too many series (${yData.length}). Only showing top ${MAX_SERIES} series in the chart. All series are still available in the table below.`
                )
            }
            return yData.slice(0, MAX_SERIES)
        }
        return yData
    }, [yData, dashboardId])

    const datasets = useMemo(() => {
        if (!ySeriesData) {
            return null
        }

        return ySeriesData.map(({ data: seriesData, settings, ...rest }, index) => {
            const seriesColor = settings?.display?.color ?? getSeriesColor(index)
            let backgroundColor = isAreaChart ? hexToRGBA(seriesColor, 0.5) : seriesColor

            // Dim non-hovered bars in stacked bar charts when shift is pressed
            if (isHighlightBarMode && hoveredDatasetIndex !== null && index !== hoveredDatasetIndex) {
                backgroundColor = hexToRGBA(seriesColor, 0.2)
            }

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
                ...(settings?.display?.trendLine && xData && yData && xData.data.length > 0 && seriesData.length > 0
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
        })
    }, [
        ySeriesData,
        xData,
        yData,
        isAreaChart,
        isHighlightBarMode,
        hoveredDatasetIndex,
        visualizationType,
        chartSettings.stackBars100,
    ])

    const { canvasRef } = useChart({
        getConfig: () => {
            const colors = getGraphColors()

            let xSeriesData: AxisSeries<string>
            let hasRightYAxis = false
            let hasLeftYAxis = false
            if (xData && ySeriesData && datasets) {
                xSeriesData = xData
                hasRightYAxis = !!ySeriesData.find((n) => n.settings?.display?.yAxisPosition === 'right')
                hasLeftYAxis =
                    !chartSettings.stackBars100 &&
                    (!hasRightYAxis || !!ySeriesData.find((n) => n.settings?.display?.yAxisPosition === 'left'))
            } else {
                return null
            }

            const data: ChartData = {
                labels: xSeriesData.data,
                datasets,
            }

            const annotations = goalLines.reduce<{
                annotations: Record<string, LineAnnotationOptions & { type: 'line' }>
            }>(
                (acc, cur, curIndex) => {
                    const line: LineAnnotationOptions = {
                        borderWidth: 2,
                        borderDash: [6, 6],
                        borderColor: resolveVariableColor(cur.borderColor),
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
                                    const tooltipEl = document.getElementById(`InsightTooltipWrapper-${tooltipId}`)

                                    if (tooltipEl) {
                                        tooltipEl.classList.add('opacity-0', 'invisible')
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

                                    const tooltipEl = document.getElementById(`InsightTooltipWrapper-${tooltipId}`)
                                    if (tooltipEl) {
                                        tooltipEl.classList.remove('opacity-0', 'invisible')
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
                { annotations: {} }
            ) as AnnotationPluginOptions

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

            const isDateAxis = xSeriesData.column.type.name === 'DATE' || xSeriesData.column.type.name === 'DATETIME'
            const xAxisTickCallback = isDateAxis
                ? createXAxisTickCallback({
                      allDays: xSeriesData.data,
                      timezone,
                  })
                : undefined

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
                        mode: isHighlightBarMode ? 'point' : 'index',
                        intersect: isHighlightBarMode,
                        external({ chart, tooltip }: { chart: Chart; tooltip: TooltipModel<ChartType> }) {
                            const canvas = chart.canvas
                            if (!canvas) {
                                return
                            }

                            const [tooltipRoot, tooltipEl] = getTooltip()
                            if (tooltip.opacity === 0) {
                                hideTooltip()
                                return
                            }

                            tooltipEl.classList.remove('above', 'below', 'no-transform')
                            tooltipEl.classList.add(tooltip.yAlign || 'no-transform')
                            showTooltip()

                            if (tooltip.body) {
                                const referenceDataPoint = tooltip.dataPoints[0]

                                // Filter series data based on highlight mode
                                let filteredSeriesData = isHighlightBarMode
                                    ? ySeriesData.filter((_, index) => index === referenceDataPoint.datasetIndex)
                                    : ySeriesData
                                const stackedSeriesTotalAtIndex =
                                    isStackedBarChart && chartSettings.stackBars100
                                        ? ySeriesData.reduce(
                                              (acc, series) => acc + (series.data[referenceDataPoint.dataIndex] ?? 0),
                                              0
                                          )
                                        : null

                                filteredSeriesData = filteredSeriesData.filter(
                                    (series) => series.data[referenceDataPoint.dataIndex] !== null
                                )

                                const tooltipData = filteredSeriesData.map((series, index) => {
                                    const seriesName =
                                        series?.settings?.display?.label ||
                                        ('column' in series ? series.column.name : series.name)
                                    const seriesIndex = isHighlightBarMode ? referenceDataPoint.datasetIndex : index
                                    return {
                                        series: seriesName,
                                        data: formatDataWithSettings(
                                            series.data[referenceDataPoint.dataIndex],
                                            series.settings
                                        ),
                                        rawData: series.data[referenceDataPoint.dataIndex],
                                        dataIndex: referenceDataPoint.dataIndex,
                                        seriesIndex: seriesIndex,
                                        stackedSeriesTotalAtIndex,
                                    }
                                })

                                let totalLabel: string | null = null
                                const tooltipTotalData = ySeriesData.filter(
                                    (n) =>
                                        n.settings?.formatting?.style !== 'percent' &&
                                        n.data[referenceDataPoint.dataIndex] !== null
                                )
                                if (
                                    tooltipTotalData.length > 1 &&
                                    chartSettings.showTotalRow !== false &&
                                    !isHighlightBarMode
                                ) {
                                    const totalRawData = tooltipTotalData.reduce((acc, cur) => {
                                        acc += cur.data[referenceDataPoint.dataIndex] ?? 0
                                        return acc
                                    }, 0)
                                    const firstSeriesSettings = tooltipTotalData[0]?.settings
                                    totalLabel = String(
                                        formatDataWithSettings(totalRawData, firstSeriesSettings) ?? totalRawData
                                    )
                                }

                                tooltipRoot.render(
                                    <div className="InsightTooltip">
                                        <div className="px-5 py-2 text-xs font-semibold border-b border-primary">
                                            {xSeriesData.data[referenceDataPoint.dataIndex]}
                                        </div>
                                        <div className="max-h-64 overflow-y-auto">
                                            <LemonTable
                                                showHeader={false}
                                                dataSource={tooltipData}
                                                columns={[
                                                    {
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
                                                        dataIndex: 'data',
                                                        render: (value, record) => {
                                                            if (isStackedBarChart && chartSettings.stackBars100) {
                                                                const total = record.stackedSeriesTotalAtIndex
                                                                if (!total) {
                                                                    return (
                                                                        <div className="series-data-cell text-right">
                                                                            {String(value)}
                                                                        </div>
                                                                    )
                                                                }
                                                                const rawData = record.rawData ?? 0
                                                                const percentageLabel: number = parseFloat(
                                                                    ((rawData / total) * 100).toFixed(1)
                                                                )

                                                                return (
                                                                    <div className="series-data-cell text-right">
                                                                        {String(value)} ({percentageLabel}%)
                                                                    </div>
                                                                )
                                                            }

                                                            return (
                                                                <div className="series-data-cell text-right">
                                                                    {String(value)}
                                                                </div>
                                                            )
                                                        },
                                                    },
                                                ]}
                                                uppercaseHeader={false}
                                                rowRibbonColor={(_datum) => {
                                                    return (
                                                        ySeriesData[_datum.seriesIndex]?.settings?.display?.color ??
                                                        getSeriesColor(_datum.seriesIndex)
                                                    )
                                                }}
                                            />
                                        </div>
                                        {totalLabel && (
                                            <div className="flex justify-between px-5 py-2 text-xs font-bold border-t border-primary">
                                                <span className="flex-1">Total</span>
                                                <span className="text-right">{totalLabel}</span>
                                            </div>
                                        )}
                                        {isBarChart && isStackedBarChart && !isHighlightBarMode && (
                                            <div className="text-xs text-muted p-2 border-t">
                                                Hold Shift (⇧) to highlight individual bars
                                            </div>
                                        )}
                                    </div>
                                )
                            }

                            const bounds = canvas.getBoundingClientRect()
                            const centerVertically = isHighlightBarMode
                            const caretY = centerVertically ? tooltip.caretY : 0
                            positionTooltip(tooltipEl, bounds, tooltip.caretX, caretY, centerVertically)
                        },
                    },
                },
                hover: {
                    mode: isBarChart ? 'point' : 'nearest',
                    axis: 'x',
                    intersect: false,
                },
                onHover: (_event: ChartEvent, elements: ActiveElement[]) => {
                    // For stacked bar charts when shift is pressed, track hovered dataset to highlight only that bar
                    if (isHighlightBarMode) {
                        const hoveredIndex = elements.length > 0 ? elements[0].datasetIndex : null
                        if (hoveredDatasetIndex !== hoveredIndex) {
                            setHoveredDatasetIndex(hoveredIndex)
                        }
                    }
                },
                scales: {
                    x: {
                        display: true,
                        beginAtZero: true,
                        stacked: isStackedBarChart,
                        ticks: {
                            ...tickOptions,
                            display: chartSettings.showXAxisTicks ?? true,
                            ...(xAxisTickCallback
                                ? { callback: xAxisTickCallback, maxRotation: 0, autoSkipPadding: 20 }
                                : {}),
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
        deps: [
            xData,
            yData,
            visualizationType,
            goalLines,
            chartSettings,
            dashboardId,
            getTooltip,
            isHighlightBarMode,
            hoveredDatasetIndex,
            timezone,
        ],
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

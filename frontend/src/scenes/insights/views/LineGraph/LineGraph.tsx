import React, { useEffect, useRef, useState } from 'react'
import ReactDOM from 'react-dom'
import { BindLogic, useValues } from 'kea'
import {
    registerables,
    ActiveElement,
    Chart,
    ChartDataset,
    ChartEvent,
    ChartItem,
    ChartOptions,
    ChartPluginsOptions,
    ChartType,
    Color,
    InteractionItem,
    TickOptions,
    Tooltip,
    TooltipModel,
    TooltipOptions,
} from 'chart.js'
import CrosshairPlugin, { CrosshairOptions } from 'chartjs-plugin-crosshair'
import 'chartjs-adapter-dayjs-3'
import { areObjectValuesEmpty, lightenDarkenColor } from '~/lib/utils'
import { getBarColorFromStatus, getGraphColors, getSeriesColor } from 'lib/colors'
import { AnnotationsOverlay, annotationsOverlayLogic } from 'lib/components/AnnotationsOverlay'
import { GraphDataset, GraphPoint, GraphPointPayload, GraphType, InsightType } from '~/types'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { lineGraphLogic } from 'scenes/insights/views/LineGraph/lineGraphLogic'
import { SeriesDatum, TooltipConfig } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { groupsModel } from '~/models/groupsModel'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { formatAggregationAxisValue, AggregationAxisFormat } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { SeriesLetter } from 'lib/components/SeriesGlyph'

if (registerables) {
    // required for storybook to work, not found in esbuild
    Chart.register(...registerables)
}
Chart.register(CrosshairPlugin)
Chart.defaults.animation['duration'] = 0

// Create positioner to put tooltip at cursor position
Tooltip.positioners.cursor = function (_, coordinates) {
    return coordinates
}

export interface LineGraphProps {
    datasets: GraphDataset[]
    hiddenLegendKeys?: Record<string | number, boolean | undefined>
    labels: string[]
    type: GraphType
    isInProgress?: boolean
    onClick?: (payload: GraphPointPayload) => void
    ['data-attr']: string
    inSharedMode?: boolean
    showPersonsModal?: boolean
    tooltip?: TooltipConfig
    isCompare?: boolean
    incompletenessOffsetFromEnd?: number // Number of data points at end of dataset to replace with a dotted line. Only used in line graphs.
    labelGroupType: number | 'people' | 'none'
    aggregationAxisFormat?: AggregationAxisFormat
}

export function ensureTooltipElement(): HTMLElement {
    let tooltipEl = document.getElementById('InsightTooltipWrapper')
    if (!tooltipEl) {
        tooltipEl = document.createElement('div')
        tooltipEl.id = 'InsightTooltipWrapper'
        tooltipEl.classList.add('InsightTooltipWrapper')
        document.body.appendChild(tooltipEl)
    }
    return tooltipEl
}

export const LineGraph = (props: LineGraphProps): JSX.Element => {
    return (
        <ErrorBoundary>
            <LineGraph_ {...props} />
        </ErrorBoundary>
    )
}

let timer: NodeJS.Timeout | null = null

function setTooltipPosition(chart: Chart, tooltipEl: HTMLElement): void {
    if (timer) {
        clearTimeout(timer)
    }
    timer = setTimeout(() => {
        const position = chart.canvas.getBoundingClientRect()

        tooltipEl.style.position = 'absolute'
        tooltipEl.style.left = position.left + window.pageXOffset + (chart.tooltip?.caretX || 0) + 8 + 'px'
        tooltipEl.style.top = position.top + window.pageYOffset + (chart.tooltip?.caretY || 0) + 8 + 'px'
    }, 25)
}

export function LineGraph_({
    datasets: _datasets,
    hiddenLegendKeys,
    labels,
    type,
    isInProgress = false,
    onClick,
    ['data-attr']: dataAttr,
    showPersonsModal = true,
    isCompare = false,
    incompletenessOffsetFromEnd = -1,
    tooltip: tooltipConfig,
    labelGroupType,
    aggregationAxisFormat = 'numeric',
}: LineGraphProps): JSX.Element {
    let datasets = _datasets

    const { createTooltipData } = useValues(lineGraphLogic)
    const { insightProps, insight, timezone } = useValues(insightLogic)
    const { aggregationLabel } = useValues(groupsModel)

    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const [myLineChart, setMyLineChart] = useState<Chart<ChartType, any, string>>()
    const [[chartWidth, chartHeight], setChartDimensions] = useState<[number, number]>([0, 0])

    const colors = getGraphColors()
    const insightType = insight.filters?.insight
    const isHorizontal = type === GraphType.HorizontalBar
    const isPie = type === GraphType.Pie
    const isBar = [GraphType.Bar, GraphType.HorizontalBar, GraphType.Histogram].includes(type)
    const isBackgroundBasedGraphType = [GraphType.Bar, GraphType.HorizontalBar, GraphType.Pie].includes(type)
    const showAnnotations = (!insightType || insightType === InsightType.TRENDS) && !isHorizontal && !isPie

    // Remove tooltip element on unmount
    useEffect(() => {
        return () => {
            const tooltipEl = document.getElementById('InsightTooltipWrapper')
            tooltipEl?.remove()
        }
    }, [])

    function processDataset(dataset: ChartDataset<any>): ChartDataset<any> {
        const mainColor = dataset?.status
            ? getBarColorFromStatus(dataset.status)
            : getSeriesColor(dataset.id, isCompare)
        const hoverColor = dataset?.status ? getBarColorFromStatus(dataset.status, true) : mainColor

        // `horizontalBar` colors are set in `ActionsHorizontalBar.tsx` and overridden in spread of `dataset` below
        return {
            borderColor: mainColor,
            hoverBorderColor: isBackgroundBasedGraphType ? lightenDarkenColor(mainColor, -20) : hoverColor,
            hoverBackgroundColor: isBackgroundBasedGraphType ? lightenDarkenColor(mainColor, -20) : undefined,
            backgroundColor: isBackgroundBasedGraphType ? mainColor : undefined,
            fill: false,
            borderWidth: isBar ? 0 : 2,
            pointRadius: 0,
            hitRadius: 0,
            order: 1,
            ...(type === GraphType.Histogram ? { barPercentage: 1 } : {}),
            ...dataset,
            hoverBorderWidth: isBar ? 0 : 2,
            hoverBorderRadius: isBar ? 0 : 2,
            type: (isHorizontal ? GraphType.Bar : type) as ChartType,
        }
    }

    // Build chart
    useEffect(() => {
        // Hide intentionally hidden keys
        if (!areObjectValuesEmpty(hiddenLegendKeys)) {
            if (isHorizontal || type === GraphType.Pie) {
                // If series are nested (for ActionsHorizontalBar and Pie), filter out the series by index
                const filterFn = (_: any, i: number): boolean => !hiddenLegendKeys?.[i]
                datasets = datasets.map((_data) => {
                    // Performs a filter transformation on properties that contain arrayed data
                    return Object.fromEntries(
                        Object.entries(_data).map(([key, val]) =>
                            Array.isArray(val) && val.length === datasets?.[0]?.actions?.length
                                ? [key, val?.filter(filterFn)]
                                : [key, val]
                        )
                    ) as GraphDataset
                })
            } else {
                datasets = datasets.filter((data) => !hiddenLegendKeys?.[data.id])
            }
        }

        // If chart is line graph, make duplicate lines and overlay to show dotted lines
        if (type === GraphType.Line && isInProgress) {
            datasets = [
                ...datasets.map((dataset) => {
                    const sliceTo = incompletenessOffsetFromEnd
                    const datasetCopy = Object.assign({}, dataset, {
                        data: [
                            ...[...(dataset.data || [])].slice(0, sliceTo),
                            ...(dataset.data?.slice(sliceTo).map(() => null) ?? []),
                        ],
                    })
                    return processDataset(datasetCopy)
                }),
                ...datasets.map((dataset) => {
                    const datasetCopy = Object.assign({}, dataset)
                    datasetCopy.dotted = true

                    // if last date is still active show dotted line
                    if (!dataset.compare || dataset.compare_label != 'previous') {
                        datasetCopy['borderDash'] = [10, 10]
                    }

                    // Nullify dates that don't have dotted line
                    const sliceFrom = incompletenessOffsetFromEnd - 1
                    datasetCopy.data = [
                        ...(datasetCopy.data?.slice(0, sliceFrom).map(() => null) ?? []),
                        ...(datasetCopy.data?.slice(sliceFrom) ?? []),
                    ] as number[]
                    return processDataset(datasetCopy)
                }),
            ]
        } else {
            datasets = datasets.map((dataset) => processDataset(dataset))
        }

        const tickOptions: Partial<TickOptions> = {
            color: colors.axisLabel as Color,
        }

        const tooltipOptions: Partial<TooltipOptions> = {
            enabled: false, // disable builtin tooltip (use custom markup)
            mode: 'nearest',
            // If bar, we want to only show the tooltip for what we're hovering over
            // to avoid confusion
            axis: isHorizontal ? 'y' : 'x',
            intersect: false,
            itemSort: (a, b) => a.label.localeCompare(b.label),
        }

        let options: ChartOptions & { plugins: ChartPluginsOptions } = {
            responsive: true,
            maintainAspectRatio: false,
            elements: {
                line: {
                    tension: 0,
                },
            },
            plugins: {
                legend: {
                    display: false,
                },
                tooltip: {
                    ...tooltipOptions,
                    external({ tooltip }: { chart: Chart; tooltip: TooltipModel<ChartType> }) {
                        if (!canvasRef.current) {
                            return
                        }

                        const tooltipEl = ensureTooltipElement()
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
                            const dataset = datasets[referenceDataPoint.datasetIndex]
                            const seriesData = createTooltipData(tooltip.dataPoints, (dp) => {
                                const hasDotted =
                                    datasets.some((d) => d.dotted) &&
                                    dp.dataIndex - datasets?.[dp.datasetIndex]?.data?.length >=
                                        incompletenessOffsetFromEnd
                                return (
                                    dp.datasetIndex >= (hasDotted ? _datasets.length : 0) &&
                                    dp.datasetIndex < (hasDotted ? _datasets.length * 2 : _datasets.length)
                                )
                            })

                            ReactDOM.render(
                                <InsightTooltip
                                    date={dataset?.days?.[tooltip.dataPoints?.[0]?.dataIndex]}
                                    timezone={timezone}
                                    seriesData={seriesData}
                                    hideColorCol={isHorizontal || !!tooltipConfig?.hideColorCol}
                                    renderCount={
                                        tooltipConfig?.renderCount ||
                                        ((value: number): string =>
                                            formatAggregationAxisValue(aggregationAxisFormat, value))
                                    }
                                    forceEntitiesAsColumns={isHorizontal}
                                    hideInspectActorsSection={!onClick || !showPersonsModal}
                                    groupTypeLabel={
                                        labelGroupType === 'people'
                                            ? 'people'
                                            : labelGroupType === 'none'
                                            ? ''
                                            : aggregationLabel(labelGroupType).plural
                                    }
                                    {...tooltipConfig}
                                />,
                                tooltipEl
                            )
                        }

                        const bounds = canvasRef.current.getBoundingClientRect()
                        const horizontalBarTopOffset = isHorizontal ? tooltip.caretY - tooltipEl.clientHeight / 2 : 0
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
                ...(!isBar
                    ? {
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
                      }
                    : {
                          crosshair: false as CrosshairOptions,
                      }),
            },
            hover: {
                mode: isBar ? 'point' : 'nearest',
                axis: isHorizontal ? 'y' : 'x',
                intersect: false,
            },
            onHover(event: ChartEvent, _: ActiveElement[], chart: Chart) {
                const nativeEvent = event.native
                if (!nativeEvent) {
                    return
                }

                const target = nativeEvent?.target as HTMLDivElement
                const point = chart.getElementsAtEventForMode(nativeEvent, 'index', { intersect: true }, true)

                if (onClick && point.length) {
                    // FIXME: Whole graph should have cursor: pointer from the get-go if it's persons modal-enabled
                    // This code gives it that style, but only once the user hovers over a data point
                    target.style.cursor = 'pointer'
                }
            },
            onClick: (event: ChartEvent, _: ActiveElement[], chart: Chart) => {
                const nativeEvent = event.native
                if (!nativeEvent) {
                    return
                }
                // Get all points along line
                const sortDirection = isHorizontal ? 'x' : 'y'
                const sortPoints = (a: InteractionItem, b: InteractionItem): number =>
                    Math.abs(a.element[sortDirection] - (event[sortDirection] ?? 0)) -
                    Math.abs(b.element[sortDirection] - (event[sortDirection] ?? 0))
                const pointsIntersectingLine = chart
                    .getElementsAtEventForMode(
                        nativeEvent,
                        isHorizontal ? 'y' : 'index',
                        {
                            intersect: false,
                        },
                        true
                    )
                    .sort(sortPoints)
                // Get all points intersecting clicked point
                const pointsIntersectingClick = chart
                    .getElementsAtEventForMode(
                        nativeEvent,
                        'point',
                        {
                            intersect: true,
                        },
                        true
                    )
                    .sort(sortPoints)

                if (!pointsIntersectingClick.length && !pointsIntersectingLine.length) {
                    return
                }

                const clickedPointNotLine = pointsIntersectingClick.length !== 0

                // Take first point when clicking a specific point.
                const referencePoint: GraphPoint = clickedPointNotLine
                    ? { ...pointsIntersectingClick[0], dataset: datasets[pointsIntersectingClick[0].datasetIndex] }
                    : { ...pointsIntersectingLine[0], dataset: datasets[pointsIntersectingLine[0].datasetIndex] }

                const crossDataset = datasets
                    .filter((_dt) => !_dt.dotted)
                    .map((_dt) => ({
                        ..._dt,
                        personUrl: _dt.persons_urls?.[referencePoint.index].url,
                        pointValue: _dt.data[referencePoint.index],
                    }))

                onClick?.({
                    points: {
                        pointsIntersectingLine: pointsIntersectingLine.map((p) => ({
                            ...p,
                            dataset: datasets[p.datasetIndex],
                        })),
                        pointsIntersectingClick: pointsIntersectingClick.map((p) => ({
                            ...p,
                            dataset: datasets[p.datasetIndex],
                        })),
                        clickedPointNotLine,
                        referencePoint,
                    },
                    index: referencePoint.index,
                    crossDataset,
                    seriesId: datasets[referencePoint.datasetIndex].id,
                })
            },
            onResize: (_, { width, height }) => setChartDimensions([width, height]),
        }

        if (type === GraphType.Bar) {
            options.scales = {
                x: {
                    beginAtZero: true,
                    stacked: true,
                    ticks: {
                        precision: 0,
                        color: colors.axisLabel as string,
                    },
                },
                y: {
                    beginAtZero: true,
                    stacked: true,
                    ticks: {
                        precision: 0,
                        color: colors.axisLabel as string,
                        callback: (value) => {
                            return formatAggregationAxisValue(aggregationAxisFormat, value)
                        },
                    },
                },
            }
        } else if (type === GraphType.Line) {
            options.scales = {
                x: {
                    beginAtZero: true,
                    display: true,
                    ticks: tickOptions,
                    grid: {
                        display: true,
                        drawOnChartArea: false,
                        borderColor: colors.axisLine as string,
                        tickLength: 12,
                    },
                },
                y: {
                    beginAtZero: true,
                    display: true,
                    ticks: {
                        precision: 0,
                        ...tickOptions,
                        callback: (value) => {
                            return formatAggregationAxisValue(aggregationAxisFormat, value)
                        },
                    },
                    grid: {
                        borderColor: colors.axisLine as string,
                    },
                },
            }
        } else if (isHorizontal) {
            options.scales = {
                x: {
                    beginAtZero: true,
                    display: true,
                    ticks: {
                        ...tickOptions,
                        precision: 0,
                        callback: (value) => {
                            return formatAggregationAxisValue(aggregationAxisFormat, value)
                        },
                    },
                },
                y: {
                    beginAtZero: true,
                    ticks: {
                        precision: 0,
                        color: colors.axisLabel as string,
                        callback: function _renderYLabel(_, i) {
                            const labelDescriptors = [
                                datasets?.[0]?.actions?.[i]?.custom_name ?? datasets?.[0]?.actions?.[i]?.name, // action name
                                datasets?.[0]?.breakdownValues?.[i], // breakdown value
                                datasets?.[0]?.compareLabels?.[i], // compare value
                            ].filter((l) => !!l)
                            return labelDescriptors.join(' - ')
                        },
                    },
                },
            }
            options.indexAxis = 'y'
        } else if (type === GraphType.Pie) {
            options = {
                responsive: true,
                maintainAspectRatio: false,
                hover: {
                    mode: 'index',
                },
                onHover: options.onHover,
                plugins: {
                    legend: {
                        display: false,
                    },
                    crosshair: false as CrosshairOptions,
                    tooltip: {
                        position: 'cursor',
                        enabled: false,
                        intersect: true,
                        external({ chart, tooltip }: { chart: Chart; tooltip: TooltipModel<ChartType> }) {
                            if (!canvasRef.current) {
                                return
                            }

                            const tooltipEl = ensureTooltipElement()
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
                                const dataset = datasets[referenceDataPoint.datasetIndex]
                                const seriesData = createTooltipData(tooltip.dataPoints, (dp) => {
                                    const hasDotted =
                                        datasets.some((d) => d.dotted) &&
                                        dp.dataIndex - datasets?.[dp.datasetIndex]?.data?.length >=
                                            incompletenessOffsetFromEnd
                                    return (
                                        dp.datasetIndex >= (hasDotted ? _datasets.length : 0) &&
                                        dp.datasetIndex < (hasDotted ? _datasets.length * 2 : _datasets.length)
                                    )
                                })

                                ReactDOM.render(
                                    <InsightTooltip
                                        date={dataset?.days?.[tooltip.dataPoints?.[0]?.dataIndex]}
                                        timezone={timezone}
                                        seriesData={seriesData}
                                        hideColorCol={isHorizontal || !!tooltipConfig?.hideColorCol}
                                        renderSeries={(value: React.ReactNode, datum: SeriesDatum) => {
                                            const hasBreakdown =
                                                datum.breakdown_value !== undefined && !!datum.breakdown_value
                                            return (
                                                <div className="datum-label-column">
                                                    <SeriesLetter
                                                        className="mr-2"
                                                        hasBreakdown={hasBreakdown}
                                                        seriesIndex={datum?.action?.order ?? datum.id}
                                                    />
                                                    <div className="flex flex-col">
                                                        {hasBreakdown && datum.breakdown_value}
                                                        {value}
                                                    </div>
                                                </div>
                                            )
                                        }}
                                        renderCount={
                                            tooltipConfig?.renderCount ||
                                            ((value: number): string => {
                                                const total = dataset.data.reduce((a: number, b: number) => a + b, 0)
                                                const percentageLabel: number = parseFloat(
                                                    ((value / total) * 100).toFixed(1)
                                                )
                                                return `${formatAggregationAxisValue(
                                                    aggregationAxisFormat,
                                                    value
                                                )} (${percentageLabel}%)`
                                            })
                                        }
                                        forceEntitiesAsColumns={isHorizontal}
                                        hideInspectActorsSection={!onClick || !showPersonsModal}
                                        groupTypeLabel={
                                            labelGroupType === 'people'
                                                ? 'people'
                                                : labelGroupType === 'none'
                                                ? ''
                                                : aggregationLabel(labelGroupType).plural
                                        }
                                        {...tooltipConfig}
                                    />,
                                    tooltipEl
                                )
                            }

                            setTooltipPosition(chart, tooltipEl)
                        },
                    },
                },
                onClick: options.onClick,
            }
        }

        const newChart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
            type: (isBar ? GraphType.Bar : type) as ChartType,
            data: { labels, datasets },
            options,
        })
        setMyLineChart(newChart)
        return () => newChart.destroy()
    }, [datasets, hiddenLegendKeys])

    return (
        <div className="LineGraph absolute w-full h-full overflow-hidden" data-attr={dataAttr}>
            <canvas ref={canvasRef} />
            {myLineChart && showAnnotations && (
                <BindLogic
                    logic={annotationsOverlayLogic}
                    props={{
                        dashboardItemId: insightProps.dashboardItemId,
                        insightNumericId: insight.id || 'new',
                    }}
                >
                    <AnnotationsOverlay
                        chart={myLineChart}
                        dates={datasets[0]?.days || []}
                        chartWidth={chartWidth}
                        chartHeight={chartHeight}
                    />
                </BindLogic>
            )}
        </div>
    )
}

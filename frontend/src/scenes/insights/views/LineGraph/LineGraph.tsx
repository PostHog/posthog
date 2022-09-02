import React, { useEffect, useMemo, useRef, useState } from 'react'
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
    TooltipModel,
    TooltipOptions,
} from 'chart.js'
import CrosshairPlugin, { CrosshairOptions } from 'chartjs-plugin-crosshair'
import 'chartjs-adapter-dayjs'
import { areObjectValuesEmpty, lightenDarkenColor } from '~/lib/utils'
import { getBarColorFromStatus, getGraphColors, getSeriesColor } from 'lib/colors'
import { AnnotationsOverlay, annotationsOverlayLogic } from 'lib/components/AnnotationsOverlay'
import './LineGraph.scss'
import { GraphDataset, GraphPoint, GraphPointPayload, GraphType } from '~/types'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { lineGraphLogic } from 'scenes/insights/views/LineGraph/lineGraphLogic'
import { TooltipConfig } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { groupsModel } from '~/models/groupsModel'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { formatAggregationAxisValue, AggregationAxisFormat } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { dayjs } from 'lib/dayjs'

if (registerables) {
    // required for storybook to work, not found in esbuild
    Chart.register(...registerables)
}
Chart.register(CrosshairPlugin)
Chart.defaults.animation['duration'] = 0

const LABEL_DAYJS_FORMATS = ['D-MMM-YYYY HH:mm', 'D-MMM-YYYY']

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

interface LineGraphCSSProperties extends React.CSSProperties {
    '--line-graph-area-left': string
    '--line-graph-area-height': string
    '--line-graph-tick-interval': string
    '--line-graph-width': string
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

    const chartRef = useRef<HTMLCanvasElement | null>(null)
    const [myLineChart, setMyLineChart] = useState<Chart<ChartType, any, string>>()

    const { width: graphWidth, height: graphHeight } = useResizeObserver({ ref: chartRef })

    const colors = getGraphColors()
    const isHorizontal = type === GraphType.HorizontalBar
    const isBar = [GraphType.Bar, GraphType.HorizontalBar, GraphType.Histogram].includes(type)
    const isBackgroundBasedGraphType = [GraphType.Bar, GraphType.HorizontalBar, GraphType.Pie]

    // Remove tooltip element on unmount
    useEffect(() => {
        return () => {
            const tooltipEl = document.getElementById('InsightTooltipWrapper')
            tooltipEl?.remove()
        }
    }, [])

    // Calculate chart content coordinates for annotations overlay positioning
    const tickInterval = useMemo<number>(() => {
        if (myLineChart) {
            const _scaleLeft = myLineChart.scales.x.left
            // NOTE: If there are lots of points on the X axis, Chart.js only renders a tick once n data points
            // so that the axis is readable. We use that mechanism to aggregate annotations for readability too.
            const tickCount = myLineChart.scales.x.ticks.length
            // We use the internal _metasets instead just taking graph area width, because it's NOT guaranteed that the
            // last tick is positioned at the right edge of the graph area. We need to find out where it is.
            const lastTickX =
                tickCount > 1
                    ? // @ts-expect-error - _metasets is not officially exposed
                      myLineChart._metasets[0].dataset._points[myLineChart.scales.x.ticks[tickCount - 1].value].x -
                      _scaleLeft
                    : 0
            const _tickInterval = lastTickX / (tickCount - 1)
            return _tickInterval
        } else {
            return 0
        }
    }, [myLineChart, graphWidth, graphHeight])

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
                        if (!chartRef.current) {
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
                                <>
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
                                    />
                                </>,
                                tooltipEl
                            )
                        }

                        const bounds = chartRef.current.getBoundingClientRect()
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
                        callbacks: {
                            label: function (context) {
                                const label: string = context.label
                                const currentValue = context.raw as number
                                // @ts-expect-error - _metasets is not officially exposed
                                const total: number = context.chart._metasets[context.datasetIndex].total
                                const percentageLabel: number = parseFloat(((currentValue / total) * 100).toFixed(1))
                                return `${label}: ${formatAggregationAxisValue(
                                    aggregationAxisFormat,
                                    currentValue
                                )} (${percentageLabel}%)`
                            },
                        },
                    },
                },
                onClick: options.onClick,
            }
        }

        const newChart = new Chart(chartRef.current?.getContext('2d') as ChartItem, {
            type: (isBar ? GraphType.Bar : type) as ChartType,
            data: { labels, datasets },
            options,
        })
        setMyLineChart(newChart)
        return () => newChart.destroy()
    }, [datasets, hiddenLegendKeys])

    return (
        <div
            className="LineGraph"
            data-attr={dataAttr}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                myLineChart
                    ? ({
                          '--line-graph-area-left': `${myLineChart.scales.x.left}px`,
                          '--line-graph-area-height': `${myLineChart.scales.x.top}px`,
                          '--line-graph-width': `${myLineChart.width}px`,
                          '--line-graph-tick-interval': `${tickInterval}px`,
                      } as LineGraphCSSProperties)
                    : undefined
            }
        >
            <canvas ref={chartRef} />
            <BindLogic
                logic={annotationsOverlayLogic}
                props={{ dashboardItemId: insightProps.dashboardItemId, insightNumericId: insight.id || 'new' }}
            >
                <AnnotationsOverlay
                    dates={
                        myLineChart
                            ? myLineChart.scales.x.ticks.map(({ label }) => dayjs(label as string, LABEL_DAYJS_FORMATS))
                            : []
                    }
                />
            </BindLogic>
        </div>
    )
}

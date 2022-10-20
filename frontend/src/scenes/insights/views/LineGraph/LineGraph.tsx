import { useEffect, useRef, useState } from 'react'
import ReactDOM from 'react-dom'
import { useValues } from 'kea'
import {
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
import { CrosshairOptions } from 'chartjs-plugin-crosshair'
import 'chartjs-adapter-dayjs-3'
import { areObjectValuesEmpty, lightenDarkenColor } from '~/lib/utils'
import { getBarColorFromStatus, getGraphColors, getSeriesColor } from 'lib/colors'
import { AnnotationsOverlay } from 'lib/components/AnnotationsOverlay'
import { FilterType, GraphDataset, GraphPoint, GraphPointPayload, GraphType, InsightType } from '~/types'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { lineGraphLogic } from 'scenes/insights/views/LineGraph/lineGraphLogic'
import { TooltipConfig } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { groupsModel } from '~/models/groupsModel'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { PieChart } from 'scenes/insights/views/LineGraph/PieChart'

import './chartjsSetup'

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
    filters?: Partial<FilterType>
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

export function onChartClick(
    event: ChartEvent,
    chart: Chart,
    datasets: GraphDataset[],
    onClick?: { (payload: GraphPointPayload): void | undefined }
): void {
    const nativeEvent = event.native
    if (!nativeEvent) {
        return
    }
    // Get all points along line
    const sortDirection = 'y'
    const sortPoints = (a: InteractionItem, b: InteractionItem): number =>
        Math.abs(a.element[sortDirection] - (event[sortDirection] ?? 0)) -
        Math.abs(b.element[sortDirection] - (event[sortDirection] ?? 0))
    const pointsIntersectingLine = chart
        .getElementsAtEventForMode(
            nativeEvent,
            'index',
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
}

export const LineGraph = (props: LineGraphProps): JSX.Element => {
    return (
        <ErrorBoundary>
            {props.type === GraphType.Pie ? <PieChart {...props} /> : <LineGraph_ {...props} />}
        </ErrorBoundary>
    )
}

export function onChartHover(
    event: ChartEvent,
    chart: Chart,
    onClick?: ((payload: GraphPointPayload) => void) | undefined
): void {
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
}

export const filterNestedDataset = (
    hiddenLegendKeys: Record<string | number, boolean | undefined> | undefined,
    datasets: GraphDataset[]
): GraphDataset[] => {
    if (!hiddenLegendKeys) {
        return datasets
    }
    // If series are nested (for ActionsHorizontalBar and Pie), filter out the series by index
    const filterFn = (_: any, i: number): boolean => !hiddenLegendKeys?.[i]
    return datasets.map((_data) => {
        // Performs a filter transformation on properties that contain arrayed data
        return Object.fromEntries(
            Object.entries(_data).map(([key, val]) =>
                Array.isArray(val) && val.length === datasets?.[0]?.actions?.length
                    ? [key, val?.filter(filterFn)]
                    : [key, val]
            )
        ) as GraphDataset
    })
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
    filters,
}: LineGraphProps): JSX.Element {
    let datasets = _datasets

    const { createTooltipData } = useValues(lineGraphLogic)
    const { insightProps, insight, timezone } = useValues(insightLogic)
    const { aggregationLabel } = useValues(groupsModel)

    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const [myLineChart, setMyLineChart] = useState<Chart<ChartType, any, string>>()

    // Relying on useResizeObserver instead of Chart's onResize because the latter was not reliable
    const { width: chartWidth, height: chartHeight } = useResizeObserver({ ref: canvasRef })

    const colors = getGraphColors()
    const insightType = insight.filters?.insight
    const isHorizontal = type === GraphType.HorizontalBar
    const isPie = type === GraphType.Pie
    if (isPie) {
        throw new Error('Use PieChart not LineGraph for this `GraphType`')
    }

    const isBar = [GraphType.Bar, GraphType.HorizontalBar, GraphType.Histogram].includes(type)
    const isBackgroundBasedGraphType = [GraphType.Bar, GraphType.HorizontalBar].includes(type)
    const showAnnotations = (!insightType || insightType === InsightType.TRENDS) && !isHorizontal

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
            if (isHorizontal) {
                datasets = filterNestedDataset(hiddenLegendKeys, datasets)
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

        const seriesMax = Math.max(...datasets.flatMap((d) => d.data).filter((n) => !!n))
        const precision = seriesMax < 5 ? 1 : seriesMax < 2 ? 2 : 0
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

        const options: ChartOptions & { plugins: ChartPluginsOptions } = {
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
                                        ((value: number): string => formatAggregationAxisValue(filters, value))
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
                onChartHover(event, chart, onClick)
            },
            onClick: (event: ChartEvent, _: ActiveElement[], chart: Chart) => {
                onChartClick(event, chart, datasets, onClick)
            },
        }

        if (type === GraphType.Bar) {
            options.scales = {
                x: {
                    beginAtZero: true,
                    stacked: true,
                    ticks: {
                        precision,
                        color: colors.axisLabel as string,
                    },
                },
                y: {
                    beginAtZero: true,
                    stacked: true,
                    ticks: {
                        precision,
                        color: colors.axisLabel as string,
                        callback: (value) => {
                            return formatAggregationAxisValue(filters, value)
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
                        precision,
                        ...tickOptions,
                        callback: (value) => {
                            return formatAggregationAxisValue(filters, value)
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
                        precision,
                        callback: (value) => {
                            return formatAggregationAxisValue(filters, value)
                        },
                    },
                },
                y: {
                    beginAtZero: true,
                    ticks: {
                        precision,
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
            {showAnnotations && myLineChart && chartWidth && chartHeight ? (
                <AnnotationsOverlay
                    chart={myLineChart}
                    dates={datasets[0]?.days || []}
                    chartWidth={chartWidth}
                    chartHeight={chartHeight}
                    dashboardItemId={insightProps.dashboardItemId}
                    insightNumericId={insight.id || 'new'}
                />
            ) : null}
        </div>
    )
}

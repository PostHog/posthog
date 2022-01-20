import React, { useEffect, useRef, useState } from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { getContext, useActions, useValues } from 'kea'
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
import { CrosshairOptions, CrosshairPlugin } from 'chartjs-plugin-crosshair'
import 'chartjs-adapter-dayjs'
import { areObjectValuesEmpty, compactNumber, lightenDarkenColor, mapRange } from '~/lib/utils'
import { getBarColorFromStatus, getChartColors, getGraphColors } from 'lib/colors'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { AnnotationMarker, Annotations, annotationsLogic } from 'lib/components/Annotations'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import './LineGraph.scss'
import { dayjs } from 'lib/dayjs'
import { AnnotationType, GraphDataset, GraphPointPayload, GraphType, IntervalType, GraphPoint } from '~/types'
import { LEGACY_LineGraph } from './LEGACY_LineGraph.jsx'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { lineGraphLogic } from 'scenes/insights/LineGraph/lineGraphLogic'
import { TooltipConfig } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { groupsModel } from '~/models/groupsModel'

//--Chart Style Options--//
Chart.register(CrosshairPlugin)
Chart.defaults.animation['duration'] = 0

//--Chart Style Options--//

interface LineGraphProps {
    datasets: GraphDataset[]
    hiddenLegendKeys?: Record<string | number, boolean | undefined>
    labels: string[]
    color: string
    type: GraphType
    isInProgress?: boolean
    onClick?: (payload: GraphPointPayload) => void
    ['data-attr']: string
    insightId?: number
    inSharedMode?: boolean
    percentage?: boolean
    interval?: IntervalType // TODO: Depecrate once LEGACY_LineGraph is removed
    totalValue?: number // TODO: Depecrate once LEGACY_LineGraph is removed
    showPersonsModal?: boolean
    tooltipPreferAltTitle?: boolean // TODO: Depecrate once LEGACY_LineGraph is removed
    tooltip?: TooltipConfig
    isCompare?: boolean
    incompletenessOffsetFromEnd?: number // Number of data points at end of dataset to replace with a dotted line. Only used in line graphs.
    labelGroupType: number | 'people' | 'none'
}

const noop = (): void => {}

export function LineGraph(props: LineGraphProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.LINE_GRAPH_V2]) {
        // @ts-ignore
        return <LEGACY_LineGraph {...props} />
    }

    const {
        datasets: _datasets,
        hiddenLegendKeys,
        labels,
        color,
        type,
        isInProgress = false,
        onClick,
        ['data-attr']: dataAttr,
        insightId,
        inSharedMode = false,
        percentage = false,
        showPersonsModal = true,
        isCompare = false,
        incompletenessOffsetFromEnd = -1,
        tooltip: tooltipConfig,
        labelGroupType,
    } = props
    let datasets = _datasets
    const { createTooltipData } = useValues(lineGraphLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const chartRef = useRef<HTMLCanvasElement | null>(null)
    const myLineChart = useRef<Chart<ChartType, any, string>>()
    const annotationsRoot = useRef<HTMLDivElement | null>(null)
    const [left, setLeft] = useState(-1)
    const [holdLeft, setHoldLeft] = useState(0)
    const [enabled, setEnabled] = useState(false)
    const [focused, setFocused] = useState(false)
    const [annotationsFocused, setAnnotationsFocused] = useState(false)
    const [labelIndex, setLabelIndex] = useState<number | null>(null)
    const [holdLabelIndex, setHoldLabelIndex] = useState<number | null>(null)
    const [selectedDayLabel, setSelectedDayLabel] = useState<string | null>(null)
    const { createAnnotation, updateDiffType, createGlobalAnnotation } = !inSharedMode
        ? useActions(annotationsLogic({ insightId }))
        : { createAnnotation: noop, updateDiffType: noop, createGlobalAnnotation: noop }

    const { annotationsList, annotationsLoading } = !inSharedMode
        ? useValues(annotationsLogic({ insightId }))
        : { annotationsList: [], annotationsLoading: false }
    const [leftExtent, setLeftExtent] = useState(0)
    const [boundaryInterval, setBoundaryInterval] = useState(0)
    const [topExtent, setTopExtent] = useState(0)
    const [annotationInRange, setInRange] = useState(false)
    const size = useWindowSize()

    const annotationsCondition =
        type === GraphType.Line && datasets?.length > 0 && !inSharedMode && datasets[0].labels?.[0] !== '1 day' // stickiness graphs

    const colors = getGraphColors(color === 'white')
    const isHorizontal = type === GraphType.HorizontalBar
    const isBar = [GraphType.Bar, GraphType.HorizontalBar, GraphType.Histogram].includes(type)
    const isBackgroundBasedGraphType = [GraphType.Bar, GraphType.HorizontalBar, GraphType.Pie]

    useEscapeKey(() => setFocused(false), [focused])

    useEffect(() => {
        buildChart()
    }, [datasets, color, hiddenLegendKeys])

    // annotation related effects

    // update boundaries and axis padding when user hovers with mouse or annotations load
    useEffect(() => {
        if (annotationsCondition && myLineChart.current?.options?.scales?.x?.grid) {
            myLineChart.current.options.scales.x.grid.tickLength = annotationInRange || focused ? 45 : 10
            myLineChart.current.update()
            calculateBoundaries()
        }
    }, [annotationsLoading, annotationsCondition, annotationsList, annotationInRange])

    useEffect(() => {
        if (annotationsCondition && (datasets?.[0]?.days?.length ?? 0) > 0) {
            const begin = dayjs(datasets[0].days?.[0])
            const end = dayjs(datasets[0].days?.[datasets[0].days.length - 1]).add(2, 'days')
            const checkBetween = (element: AnnotationType): boolean =>
                dayjs(element.date_marker).isSameOrBefore(end) && dayjs(element.date_marker).isSameOrAfter(begin)
            setInRange(annotationsList.some(checkBetween))
        }
    }, [datasets, annotationsList, annotationsCondition])

    // recalculate diff if interval type selection changes
    useEffect(() => {
        if (annotationsCondition && datasets?.[0]?.days) {
            updateDiffType(datasets[0].days)
        }
    }, [datasets, type, annotationsCondition])

    // update only boundaries when window size changes or chart type changes
    useEffect(() => {
        if (annotationsCondition) {
            calculateBoundaries()
        }
    }, [myLineChart.current, size, type, annotationsCondition])

    // Remove tooltip element on unmount
    useEffect(() => {
        return () => {
            const tooltipEl = document.getElementById('ph-graph-tooltip')
            tooltipEl?.remove()
        }
    }, [])

    function calculateBoundaries(): void {
        if (myLineChart.current) {
            const boundaryLeftExtent = myLineChart.current.scales.x.left
            const boundaryRightExtent = myLineChart.current.scales.x.right
            const boundaryTicks = myLineChart.current.scales.x.ticks.length
            const boundaryDelta = boundaryRightExtent - boundaryLeftExtent
            const _boundaryInterval = boundaryDelta / (boundaryTicks - 1)
            const boundaryTopExtent = myLineChart.current.scales.x.top + 8
            setLeftExtent(boundaryLeftExtent)
            setBoundaryInterval(_boundaryInterval)
            setTopExtent(boundaryTopExtent)
        }
    }

    function processDataset(dataset: ChartDataset<any>): ChartDataset<any> {
        const colorList = getChartColors(color || 'white', _datasets.length, isCompare)
        const mainColor = dataset?.status
            ? getBarColorFromStatus(dataset.status)
            : colorList[(dataset.id ?? 0) % (_datasets?.length ?? 1)]
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

    function buildChart(): void {
        const myChartRef = chartRef.current?.getContext('2d')

        if (typeof myLineChart.current !== 'undefined') {
            myLineChart.current.destroy()
        }

        // Hide intentionally hidden keys
        if (!areObjectValuesEmpty(hiddenLegendKeys)) {
            if (isHorizontal) {
                // If series are nested (for ActionsHorizontalBar only), filter out the series by index
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
                    datasetCopy['borderDash'] = [10, 10]

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
                    external(args: { chart: Chart; tooltip: TooltipModel<ChartType> }) {
                        let tooltipEl = document.getElementById('ph-graph-tooltip')
                        const { tooltip } = args

                        // Create element on first render
                        if (!tooltipEl) {
                            tooltipEl = document.createElement('div')
                            tooltipEl.id = 'ph-graph-tooltip'
                            tooltipEl.classList.add('ph-graph-tooltip')
                            document.body.appendChild(tooltipEl)
                        }
                        if (tooltip.opacity === 0) {
                            tooltipEl.style.opacity = '0'
                            return
                        }

                        if (!chartRef.current) {
                            return
                        }

                        // Set caret position
                        // Reference: https://www.chartjs.org/docs/master/configuration/tooltip.html
                        tooltipEl.classList.remove('above', 'below', 'no-transform')
                        tooltipEl.classList.add(tooltip.yAlign || 'no-transform')
                        const bounds = chartRef.current.getBoundingClientRect()
                        const chartClientLeft = bounds.left + window.pageXOffset

                        tooltipEl.style.opacity = '1'
                        tooltipEl.style.position = 'absolute'
                        tooltipEl.style.padding = '10px'
                        tooltipEl.style.pointerEvents = 'none'

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
                                <Provider store={getContext().store}>
                                    <InsightTooltip
                                        date={dataset?.days?.[tooltip.dataPoints?.[0]?.dataIndex]}
                                        seriesData={seriesData}
                                        hideColorCol={isHorizontal}
                                        forceEntitiesAsColumns={isHorizontal}
                                        hideInspectActorsSection={!(onClick && showPersonsModal)}
                                        groupTypeLabel={
                                            labelGroupType === 'people'
                                                ? 'people'
                                                : labelGroupType === 'none'
                                                ? ''
                                                : aggregationLabel(labelGroupType).plural
                                        }
                                        {...tooltipConfig}
                                    />
                                </Provider>,
                                tooltipEl
                            )
                        }

                        const horizontalBarTopOffset = isHorizontal ? tooltip.caretY - tooltipEl.clientHeight / 2 : 0
                        const tooltipClientTop = bounds.top + window.pageYOffset + horizontalBarTopOffset

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
                    target.style.cursor = 'pointer'
                } else {
                    target.style.cursor = 'default'
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
                            return compactNumber(Number(value))
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
                        display: false,
                        borderColor: colors.axisLine as string,
                        tickLength: annotationInRange || focused ? 45 : 10,
                    },
                },
                y: {
                    beginAtZero: true,
                    display: true,
                    ticks: {
                        precision: 0,
                        ...(percentage
                            ? {
                                  callback: function (value) {
                                      const numVal = Number(value)
                                      const fixedValue = numVal < 1 ? numVal.toFixed(2) : numVal.toFixed(0)
                                      return `${fixedValue}%` // convert it to percentage
                                  },
                              }
                            : {
                                  ...tickOptions,
                                  callback: (value) => {
                                      return compactNumber(Number(value))
                                  },
                              }),
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
                            return compactNumber(Number(value))
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
                },
                onClick: options.onClick,
            }
        }

        myLineChart.current = new Chart(myChartRef as ChartItem, {
            type: (isBar ? GraphType.Bar : type) as ChartType,
            data: { labels, datasets },
            options,
        })
    }

    return (
        <div
            className="graph-container"
            data-attr={dataAttr}
            onMouseMove={(e) => {
                setEnabled(true)
                if (annotationsCondition && myLineChart.current) {
                    const rect = e.currentTarget.getBoundingClientRect(),
                        offsetX = e.clientX - rect.left,
                        offsetY = e.clientY - rect.top
                    if (offsetY < topExtent - 30 && !focused && !annotationsFocused) {
                        setEnabled(false)
                        setLeft(-1)
                        return
                    }

                    const xAxis = myLineChart.current.scales.x,
                        _leftExtent = xAxis.left,
                        _rightExtent = xAxis.right,
                        ticks = xAxis.ticks.length,
                        delta = _rightExtent - _leftExtent,
                        _interval = delta / (ticks - 1)
                    if (offsetX < _leftExtent - _interval / 2) {
                        return
                    }
                    const index = mapRange(offsetX, _leftExtent - _interval / 2, _rightExtent + _interval / 2, 0, ticks)
                    if (index >= 0 && index < ticks && offsetY >= topExtent - 30) {
                        setLeft(index * _interval + _leftExtent)
                        setLabelIndex(index)
                    }
                }
            }}
            onMouseLeave={() => setEnabled(false)}
        >
            <canvas ref={chartRef} />
            <div className="annotations-root" ref={annotationsRoot} />
            {annotationsCondition && (
                <Annotations
                    dates={datasets[0].days ?? []}
                    leftExtent={leftExtent}
                    interval={boundaryInterval}
                    topExtent={topExtent}
                    insightId={insightId}
                    currentDateMarker={
                        focused || annotationsFocused
                            ? selectedDayLabel
                            : enabled && labelIndex
                            ? datasets[0].days?.[labelIndex]
                            : null
                    }
                    onClick={() => {
                        setFocused(false)
                        setAnnotationsFocused(true)
                    }}
                    onClose={() => {
                        setAnnotationsFocused(false)
                    }}
                    graphColor={color}
                    color={colors.annotationColor}
                    accessoryColor={colors.annotationAccessoryColor}
                />
            )}
            {annotationsCondition && !annotationsFocused && (enabled || focused) && left >= 0 && (
                <AnnotationMarker
                    insightId={insightId}
                    currentDateMarker={focused ? selectedDayLabel : labelIndex ? datasets[0].days?.[labelIndex] : null}
                    onClick={() => {
                        setFocused(true)
                        setHoldLeft(left)
                        setHoldLabelIndex(labelIndex)
                        setSelectedDayLabel(labelIndex ? datasets[0].days?.[labelIndex] ?? null : null)
                    }}
                    getPopupContainer={
                        annotationsRoot?.current ? () => annotationsRoot.current as HTMLDivElement : undefined
                    }
                    onCreateAnnotation={(textInput, applyAll) => {
                        const date = holdLabelIndex ? datasets[0].days?.[holdLabelIndex] : null
                        if (date) {
                            if (applyAll) {
                                createGlobalAnnotation(textInput, date, insightId)
                            } else {
                                createAnnotation(textInput, date)
                            }
                        }
                    }}
                    onClose={() => setFocused(false)}
                    dynamic={true}
                    left={(focused ? holdLeft : left) - 12.5}
                    top={topExtent}
                    label={'Add Note'}
                    graphColor={color}
                    color={colors.annotationColor}
                    accessoryColor={colors.annotationAccessoryColor}
                />
            )}
        </div>
    )
}

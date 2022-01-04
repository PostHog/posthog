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
    TooltipItem,
    TooltipModel,
    TooltipOptions,
} from 'chart.js'
import { CrosshairOptions, CrosshairPlugin } from 'chartjs-plugin-crosshair'
import 'chartjs-adapter-dayjs'
import { compactNumber, lightenDarkenColor, mapRange } from '~/lib/utils'
import { getBarColorFromStatus, getChartColors, getGraphColors } from 'lib/colors'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { AnnotationMarker, Annotations, annotationsLogic } from 'lib/components/Annotations'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import './LineGraph.scss'
import { LEGACY_InsightTooltip } from '../InsightTooltip/LEGACY_InsightTooltip'
import { dayjs } from 'lib/dayjs'
import { AnnotationType, GraphDataset, GraphPointPayload, GraphType, IntervalType, GraphPoint } from '~/types'
import { InsightLabel } from 'lib/components/InsightLabel'
import { LEGACY_LineGraph } from './LEGACY_LineGraph.jsx'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'

//--Chart Style Options--//
Chart.register(CrosshairPlugin)
Chart.defaults.animation['duration'] = 0
//--Chart Style Options--//

interface LineGraphProps {
    datasets: GraphDataset[]
    visibilityMap?: Record<string | number, any>
    labels: string[]
    color: string
    type: GraphType
    isInProgress?: boolean
    onClick?: (payload: GraphPointPayload) => void
    ['data-attr']: string
    insightId?: number
    inSharedMode?: boolean
    percentage?: boolean
    interval?: IntervalType
    totalValue?: number
    showPersonsModal?: boolean
    tooltipPreferAltTitle?: boolean
    isCompare?: boolean
    incompletenessOffsetFromEnd?: number // Number of data points at end of dataset to replace with a dotted line. Only used in line graphs.
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
        visibilityMap,
        labels,
        color,
        type,
        isInProgress = false,
        onClick,
        ['data-attr']: dataAttr,
        insightId,
        inSharedMode = false,
        percentage = false,
        interval = undefined,
        totalValue,
        showPersonsModal = true,
        tooltipPreferAltTitle = false,
        isCompare = false,
        incompletenessOffsetFromEnd = -1,
    } = props
    let datasets = _datasets
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
    }, [datasets, color, visibilityMap])

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

    function processDataset(dataset: ChartDataset<any>, index: number): ChartDataset<any> {
        const colorList = getChartColors(color || 'white', datasets.length, isCompare)
        const mainColor = dataset?.status ? getBarColorFromStatus(dataset.status) : colorList[index % colorList.length]
        const hoverColor = dataset?.status ? getBarColorFromStatus(dataset.status, true) : mainColor

        // `horizontalBar` colors are set in `ActionsHorizontalBar.tsx` and overriden in spread of `dataset` below

        return {
            borderColor: mainColor,
            hoverBorderColor: isBackgroundBasedGraphType ? lightenDarkenColor(mainColor, -20) : hoverColor,
            hoverBackgroundColor: isBackgroundBasedGraphType ? lightenDarkenColor(mainColor, -20) : undefined,
            backgroundColor: isBackgroundBasedGraphType ? mainColor : undefined,
            fill: false,
            borderWidth: isBar ? 0 : 2,
            pointRadius: 0,
            hitRadius: 0,
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

        // if chart is line graph, make duplicate lines and overlay to show dotted lines
        if (type === GraphType.Line) {
            datasets = [
                ...datasets.map((dataset, index) => {
                    const sliceTo = incompletenessOffsetFromEnd || (dataset.data?.length ?? 0)
                    const datasetCopy = Object.assign({}, dataset, {
                        data: [...(dataset.data || [])].slice(0, sliceTo),
                        labels: [...(dataset.labels || [])].slice(0, sliceTo),
                        days: [...(dataset.days || [])].slice(0, sliceTo),
                    })
                    console.log('SLICE to', sliceTo, dataset, datasetCopy)
                    return processDataset(datasetCopy, index)
                }),
                ...datasets.map((dataset, index) => {
                    const datasetCopy = Object.assign({}, dataset)
                    datasetCopy.dotted = true

                    // if last date is still active show dotted line
                    if (isInProgress) {
                        datasetCopy['borderDash'] = [10, 10]
                    }

                    // Nullify dates that don't have dotted line
                    const sliceFrom = incompletenessOffsetFromEnd - 1 || (datasetCopy.data?.length ?? 0)
                    datasetCopy.data = [
                        ...(datasetCopy.data?.slice(0, sliceFrom).map(() => null) ?? []),
                        ...(datasetCopy.data?.slice(sliceFrom) ?? []),
                    ] as number[]

                    console.log('SLICE from', sliceFrom, dataset, datasetCopy)

                    return processDataset(datasetCopy, index)
                }),
            ]
            if (visibilityMap && Object.keys(visibilityMap).length > 0) {
                datasets = datasets.filter((data) => visibilityMap[data.id])
            }
        } else {
            datasets = datasets.map((dataset, index) => processDataset(dataset, index))
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
            scaleShowHorizontalLines: false,
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
                            tooltipEl.style.opacity = '1'
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

                            ReactDOM.render(
                                <Provider store={getContext().store}>
                                    {featureFlags[FEATURE_FLAGS.NEW_INSIGHT_TOOLTIPS] ? (
                                        <InsightTooltip
                                            date={dataset?.days?.[tooltip.dataPoints?.[0]?.dataIndex]}
                                            seriesData={tooltip.dataPoints
                                                ?.filter((dp: any) => !dp?.dataset?.dotted)
                                                ?.map((dp, idx) => {
                                                    const pointDataset = (dp?.dataset ?? {}) as GraphDataset
                                                    return {
                                                        id: idx,
                                                        dataIndex: dp.dataIndex,
                                                        datasetIndex: dp.datasetIndex,
                                                        breakdown_value: pointDataset?.breakdown_value ?? undefined,
                                                        compare_value: pointDataset?.compare_label ?? undefined,
                                                        action:
                                                            pointDataset?.action ??
                                                            pointDataset?.actions?.[0] ??
                                                            undefined,
                                                        color: pointDataset.backgroundColor as string,
                                                        count: pointDataset?.data?.[dp.dataIndex] ?? 0,
                                                    }
                                                })}
                                            hideInspectActorsSection={!(onClick && showPersonsModal)}
                                        />
                                    ) : (
                                        <LEGACY_InsightTooltip
                                            referenceDate={
                                                !dataset.compare
                                                    ? dataset.days?.[referenceDataPoint.dataIndex]
                                                    : undefined
                                            }
                                            altTitle={
                                                tooltip.title && (dataset.compare || tooltipPreferAltTitle)
                                                    ? tooltip.title[0]
                                                    : ''
                                            } // When comparing we show the whole range for clarity; when on stickiness we show the relative timeframe (e.g. `5 days`)
                                            interval={interval}
                                            bodyLines={tooltip.body
                                                .flatMap(({ lines }) => lines)
                                                .map((component, idx) => ({
                                                    id: idx,
                                                    component,
                                                }))}
                                            preferAltTitle={tooltipPreferAltTitle}
                                            hideHeader={isHorizontal}
                                            inspectPersonsLabel={onClick && showPersonsModal}
                                        />
                                    )}
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
                    callbacks: {
                        // @ts-ignore: label callback is typed to return string | string[], but practically can return ReactNode
                        label(tooltipItem: TooltipItem<any>) {
                            const entityData = tooltipItem.dataset
                            const tooltipDatasets = this.dataPoints
                                .map((point) => point.dataset as ChartDataset<any>)
                                .filter((dt) => !dt.dotted)
                            if (!(tooltipItem.dataIndex === entityData.data.length - 1)) {
                                return ''
                            }

                            console.log('DATASETS', tooltipDatasets)

                            const label = entityData.chartLabel || entityData.label || tooltipItem.label || ''
                            const action =
                                entityData.action || (entityData.actions && entityData.actions[tooltipItem.dataIndex])

                            let value = tooltipItem.formattedValue.toLocaleString()
                            const actionObjKey = isHorizontal ? 'actions' : 'action'

                            if (isHorizontal && totalValue) {
                                const perc = Math.round((Number(tooltipItem.raw) / totalValue) * 100)
                                value = `${tooltipItem.label.toLocaleString()} (${perc}%)`
                            }

                            let showCountedByTag = false
                            let numberOfSeries = 1
                            if (tooltipDatasets.find((item) => item[actionObjKey])) {
                                // The above statement will always be true except in Sessions tab
                                showCountedByTag = !!tooltipDatasets.find(
                                    ({ [actionObjKey]: actionObj }) => actionObj?.math && actionObj.math !== 'total'
                                )
                                numberOfSeries = new Set(
                                    tooltipDatasets.flatMap(({ [actionObjKey]: actionObj }) => actionObj?.order)
                                ).size
                            }

                            // This could either be a color or an array of colors (`horizontalBar`)
                            const colorSet = entityData.backgroundColor || entityData.borderColor
                            return (
                                <InsightLabel
                                    action={action}
                                    seriesColor={isHorizontal ? colorSet[tooltipItem.dataIndex] : colorSet}
                                    value={value}
                                    fallbackName={label}
                                    showCountedByTag={showCountedByTag}
                                    hasMultipleSeries={numberOfSeries > 1}
                                    breakdownValue={
                                        entityData.breakdownValues // Used in `horizontalBar`
                                            ? entityData.breakdownValues[tooltipItem.dataIndex] === ''
                                                ? 'None'
                                                : entityData.breakdownValues[tooltipItem.dataIndex]
                                            : entityData.breakdown_value === ''
                                            ? 'None'
                                            : entityData.breakdown_value
                                    }
                                    seriesStatus={entityData.status}
                                />
                            )
                        },
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
                                  color: colors.crosshair,
                                  width: 1,
                              },
                          },
                      }
                    : {
                          crosshair: false,
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

                // For now, take first point when clicking a specific point.
                // TODO: Implement case when if the entire line was clicked, show people for that entire day across actions.
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
                    min: 0,
                    beginAtZero: true,
                    stacked: true,
                    ticks: {
                        precision: 0,
                        color: colors.axisLabel as string,
                    },
                },
                y: {
                    min: 0,
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
                    min: 0,
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
                    min: 0,
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
                    min: 0,
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
                    min: 0,
                    beginAtZero: true,
                    ticks: {
                        precision: 0,
                        color: colors.axisLabel as string,
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

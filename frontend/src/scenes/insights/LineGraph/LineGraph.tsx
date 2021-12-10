import React, { useState, useEffect, useRef } from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { BuiltLogic, getContext, useActions, useValues } from 'kea'
import {
    Chart,
    ChartDataset,
    ChartOptions,
    ChartType,
    DefaultDataPoint,
    Color,
    TickOptions,
    TooltipOptions,
    TooltipModel,
    TooltipItem,
} from 'chart.js'
import 'chartjs-adapter-dayjs'
import { compactNumber, lightenDarkenColor, noop, mapRange } from '~/lib/utils'
import { getBarColorFromStatus, getChartColors, getGraphColors } from 'lib/colors'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { toast } from 'react-toastify'
import { AnnotationMarker, annotationsLogic, renderAnnotations } from 'lib/components/Annotations'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import './LineGraph.scss'
import { InsightLabel } from 'lib/components/InsightLabel'
import { InsightTooltip } from '../InsightTooltip/InsightTooltip'
import { dayjs } from 'lib/dayjs'
import { AnnotationType, GraphPointPayload, GraphTypes, InsightShortId, IntervalType, TrendResult } from '~/types'

//--Chart Style Options--//
console.log('CHART DEFAULTS', Chart.defaults)
Chart.defaults.plugins.legend.display = false
Chart.defaults.animation.duration = 0
Chart.defaults.elements.line.tension = 0
//--Chart Style Options--//

interface LineGraphProps {
    datasets: (ChartDataset<any> & Partial<Pick<TrendResult, 'count' | 'label' | 'days' | 'labels' | 'data'>>)[]
    visibilityMap?: Record<string | number, any>
    labels: string[]
    color: string
    type: string
    isInProgress?: boolean
    onClick?: (payload: GraphPointPayload) => void
    ['data-attr']: string
    dashboardItemId?: InsightShortId | null
    inSharedMode: boolean
    percentage?: boolean
    interval?: IntervalType
    totalValue?: number
    showPersonsModal?: boolean
    tooltipPreferAltTitle?: boolean
    isCompare?: boolean
}

export function LineGraph({
    datasets,
    visibilityMap,
    labels,
    color,
    type,
    isInProgress = false,
    onClick,
    ['data-attr']: dataAttr,
    dashboardItemId /* used only for annotations, not to init any other logic */,
    inSharedMode,
    percentage = false,
    interval = undefined,
    totalValue,
    showPersonsModal = true,
    tooltipPreferAltTitle = false,
    isCompare = false,
}: LineGraphProps): JSX.Element {
    const chartRef = useRef<HTMLCanvasElement | null>(null)
    const myLineChart = useRef<Chart<ChartType, number[] | undefined, string>>()
    const annotationsRoot = useRef<HTMLDivElement | null>(null)
    const [left, setLeft] = useState(-1)
    const [holdLeft, setHoldLeft] = useState(0)
    const [enabled, setEnabled] = useState(false)
    const [focused, setFocused] = useState(false)
    const [annotationsFocused, setAnnotationsFocused] = useState(false)
    const [labelIndex, setLabelIndex] = useState(null)
    const [holdLabelIndex, setHoldLabelIndex] = useState(null)
    const [selectedDayLabel, setSelectedDayLabel] = useState(null)
    const { createAnnotation, createAnnotationNow, updateDiffType, createGlobalAnnotation } = !inSharedMode
        ? useActions(annotationsLogic({ insightId: dashboardItemId || undefined }) as BuiltLogic)
        : { createAnnotation: noop, createAnnotationNow: noop, updateDiffType: noop, createGlobalAnnotation: noop }

    const { annotationsList, annotationsLoading } = !inSharedMode
        ? useValues(annotationsLogic({ insightId: dashboardItemId || undefined }) as BuiltLogic)
        : { annotationsList: [], annotationsLoading: false }
    const [leftExtent, setLeftExtent] = useState(0)
    const [boundaryInterval, setBoundaryInterval] = useState(0)
    const [topExtent, setTopExtent] = useState(0)
    const [annotationInRange, setInRange] = useState(false)
    const [tooltipVisible, setTooltipVisible] = useState(false)
    const size = useWindowSize()

    const annotationsCondition =
        type === 'line' && datasets?.length > 0 && !inSharedMode && datasets[0].labels?.[0] !== '1 day' // stickiness graphs

    const colors = getGraphColors(color === 'white')

    useEscapeKey(() => setFocused(false), [focused])

    useEffect(() => {
        buildChart()
    }, [datasets, color, visibilityMap])

    // Hacky! - Chartjs doesn't internally call tooltip callback on mouseout from right border.
    // Let's manually remove tooltips when the chart is being hovered over. #5061
    useEffect(() => {
        const removeTooltip = (): void => {
            const tooltipEl = document.getElementById('ph-graph-tooltip')

            if (tooltipEl && !tooltipVisible) {
                tooltipEl.style.opacity = '0'
            }
        }
        removeTooltip()
        return removeTooltip // remove tooltip on component unmount
    }, [tooltipVisible])

    // annotation related effects

    // update boundaries and axis padding when user hovers with mouse or annotations load
    useEffect(() => {
        if (annotationsCondition && myLineChart.current?.options.layout) {
            myLineChart.current.options.layout.padding = annotationInRange || focused ? { bottom: 35 } : {}
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

        // `horizontalBar` colors are set in `ActionsBarValueGraph.tsx` and overriden in spread of `dataset` below
        const BACKGROUND_BASED_CHARTS = ['bar', 'doughnut']

        return {
            borderColor: mainColor,
            hoverBorderColor: BACKGROUND_BASED_CHARTS.includes(type) ? lightenDarkenColor(mainColor, -20) : hoverColor,
            hoverBackgroundColor: BACKGROUND_BASED_CHARTS.includes(type)
                ? lightenDarkenColor(mainColor, -20)
                : undefined,
            backgroundColor: BACKGROUND_BASED_CHARTS.includes(type) ? mainColor : undefined,
            fill: false,
            borderWidth: 2,
            pointRadius: 0,
            pointHoverBorderWidth: 2,
            pointHitRadius: 8,
            ...dataset,
            type: (type === 'horizontalBar' ? GraphTypes.Bar : type) as ChartType,
        }
    }

    function buildChart(): void {
        const myChartRef = chartRef.current?.getContext('2d')

        if (typeof myLineChart.current !== 'undefined') {
            myLineChart.current.destroy()
        }

        // if chart is line graph, make duplicate lines and overlay to show dotted lines
        const isLineGraph = type === 'line'
        if (isLineGraph) {
            datasets = [
                ...datasets.map((dataset, index) => {
                    const datasetCopy = Object.assign({}, dataset)
                    const data = [...(dataset.data || [])]
                    const _labels = [...(dataset.labels || [])]
                    const days = [...(dataset.days || [])]
                    data.pop()
                    _labels.pop()
                    days.pop()
                    datasetCopy.data = data
                    datasetCopy.labels = _labels
                    datasetCopy.days = days
                    return processDataset(datasetCopy, index)
                }),
                ...datasets.map((dataset, index) => {
                    const datasetCopy = Object.assign({}, dataset)
                    const datasetLength = datasetCopy.data?.length ?? 0
                    datasetCopy.dotted = true

                    // if last date is still active show dotted line
                    if (isInProgress) {
                        datasetCopy.borderDash = [10, 10]
                    }

                    datasetCopy.data =
                        datasetCopy.data?.length > 2
                            ? datasetCopy.data.map((datum: DefaultDataPoint<any>, idx: number) =>
                                  idx === datasetLength - 1 || idx === datasetLength - 2 ? datum : null
                              )
                            : datasetCopy.data
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
            showLabelBackdrop: true,
            backdropColor: 'red',
        }

        const tooltipOptions: Partial<TooltipOptions> = {
            enabled: false, // disable builtin tooltip (use custom markup)
            mode: 'nearest',
            // If bar, we want to only show the tooltip for what we're hovering over
            // to avoid confusion
            axis: type === 'horizontalBar' ? 'xy' : 'x',
            intersect: type === 'horizontalBar',
            itemSort: (a, b) => a.label.localeCompare(b.label),
        }

        let options: ChartOptions = {
            responsive: true,
            maintainAspectRatio: false,
            scaleShowHorizontalLines: false,
            tooltips: tooltipOptions,
            plugins: {
                tooltip: {
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

                        // Set caret position
                        // Reference: https://www.chartjs.org/docs/master/configuration/tooltip.html
                        if (!chartRef.current) {
                            return
                        }

                        tooltipEl.classList.remove('above', 'below', 'no-transform')
                        tooltipEl.classList.add(tooltip.yAlign || 'no-transform')
                        const bounds = chartRef.current.getBoundingClientRect()
                        const chartClientLeft = bounds.left + window.pageXOffset

                        tooltipEl.style.opacity = '1'
                        tooltipEl.style.position = 'absolute'
                        tooltipEl.style.padding = tooltip.padding + 'px'
                        tooltipEl.style.pointerEvents = 'none'

                        if (tooltip.body) {
                            const referenceDataPoint = tooltip.dataPoints[0] // Use this point as reference to get the date
                            const dataset = datasets[referenceDataPoint.datasetIndex]

                            const altTitle =
                                tooltip.title && (dataset.compare || tooltipPreferAltTitle) ? tooltip.title[0] : '' // When comparing we show the whole range for clarity; when on stickiness we show the relative timeframe (e.g. `5 days`)
                            const referenceDate = !dataset.compare ? dataset.days[referenceDataPoint.index] : undefined
                            const bodyLines = tooltip.body
                                .flatMap(({ lines }) => lines)
                                .map((component, idx) => ({
                                    id: idx,
                                    component,
                                }))

                            ReactDOM.render(
                                <Provider store={getContext().store}>
                                    <InsightTooltip
                                        altTitle={altTitle}
                                        referenceDate={referenceDate}
                                        interval={interval}
                                        bodyLines={bodyLines}
                                        inspectPersonsLabel={onClick && showPersonsModal}
                                        preferAltTitle={tooltipPreferAltTitle}
                                        hideHeader={type === 'horizontalBar'}
                                    />
                                </Provider>,
                                tooltipEl
                            )
                        }

                        const horizontalBarTopOffset =
                            type === 'horizontalBar' ? tooltip.caretY - tooltipEl.clientHeight / 2 : 0
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
                        label(tooltipItem: TooltipItem<any>): React.ReactNode {
                            const entityData = tooltipItem.dataset
                            if (entityData.dotted && !(tooltipItem.dataIndex === entityData.data.length - 1)) {
                                return ''
                            }

                            const label = entityData.chartLabel || entityData.label || tooltipItem.label || ''
                            const action =
                                entityData.action || (entityData.actions && entityData.actions[tooltipItem.index])

                            let value = tooltipItem.yLabel.toLocaleString()
                            const actionObjKey = type === 'horizontalBar' ? 'actions' : 'action'

                            if (type === 'horizontalBar' && totalValue) {
                                const perc = Math.round((tooltipItem.label / totalValue) * 100)
                                value = `${tooltipItem.label.toLocaleString()} (${perc}%)`
                            }

                            let showCountedByTag = false
                            let numberOfSeries = 1
                            if (data.datasets.find((item) => item[actionObjKey])) {
                                // The above statement will always be true except in Sessions tab
                                showCountedByTag = !!data.datasets.find(
                                    ({ [actionObjKey]: { math } }) => math && math !== 'total'
                                )
                                numberOfSeries = new Set(
                                    data.datasets.flatMap(({ [actionObjKey]: { order } }) => order)
                                ).size
                            }

                            // This could either be a color or an array of colors (`horizontalBar`)
                            const colorSet = entityData.backgroundColor || entityData.borderColor
                            return (
                                <InsightLabel
                                    action={action}
                                    seriesColor={type === 'horizontalBar' ? colorSet[tooltipItem.index] : colorSet}
                                    value={value}
                                    fallbackName={label}
                                    showCountedByTag={showCountedByTag}
                                    hasMultipleSeries={numberOfSeries > 1}
                                    breakdownValue={
                                        entityData.breakdownValues // Used in `horizontalBar`
                                            ? entityData.breakdownValues[tooltipItem.index] === ''
                                                ? 'None'
                                                : entityData.breakdownValues[tooltipItem.index]
                                            : entityData.breakdown_value === ''
                                            ? 'None'
                                            : entityData.breakdown_value
                                    }
                                    seriesStatus={entityData.status}
                                    useCustomName
                                />
                            )
                        },
                    },
                },
                ...(type !== 'horizontalBar' && !datasets?.[0]?.status
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
                mode: 'nearestX',
                axis: 'xy',
                intersect: false,
                onHover(evt: Event, _, chart) {
                    const point = chart.getElementAtEvent(evt)
                    if (onClick && point.length) {
                        evt.target.style.cursor = 'pointer'
                    } else {
                        evt.target.style.cursor = 'default'
                    }
                    if (evt.type === 'mouseout') {
                        setTooltipVisible(false)
                    } else {
                        setTooltipVisible(true)
                    }
                },
            },
            onClick: (evt, _, chart) => {
                const point = chart.getElementsAtEventForMode(
                    evt as unknown as Event,
                    'point',
                    {
                        intersect: true,
                    },
                    true
                )?.[0]

                if (point && onClick) {
                    const dataset = datasets[point.datasetIndex]
                    const indexExists = typeof point.index !== 'undefined'
                    onClick({
                        point,
                        dataset,
                        index: point.index,
                        label: indexExists && dataset.labels ? dataset.labels[point.index] : undefined,
                        day: indexExists && dataset.days ? dataset.days[point.index] : undefined,
                        value: indexExists && dataset.data ? dataset.data[point.index] : undefined,
                    })
                }
            },
        }

        if (type === 'bar') {
            options.scales = {
                x: {
                    min: 0,
                    precision: 0,
                    beginAtZero: true,
                    stacked: true,
                    ticks: {
                        color: colors.axisLabel,
                    },
                },
                y: {
                    min: 0,
                    precision: 0,
                    beginAtZero: true,
                    stacked: true,
                    ticks: {
                        color: colors.axisLabel,
                        callback: (value) => {
                            return compactNumber(value)
                        },
                    },
                },
            }
        } else if (type === 'line') {
            options.scales = {
                x: {
                    min: 0,
                    beginAtZero: true,
                    display: true,
                    gridLines: { lineWidth: 0, color: colors.axisLine, zeroLineColor: colors.axis },
                    ticks: {
                        ...tickOptions,
                        padding: annotationsLoading || !annotationInRange ? 0 : 35,
                    },
                },
                y: {
                    min: 0,
                    precision: 0,
                    beginAtZero: true,
                    display: true,
                    gridLines: { color: colors.axisLine, zeroLineColor: colors.axis },
                    ticks: percentage
                        ? {
                              callback: function (value) {
                                  const fixedValue = value < 1 ? value.toFixed(2) : value.toFixed(0)
                                  return `${fixedValue}%` // convert it to percentage
                              },
                          }
                        : {
                              ...tickOptions,
                              callback: (value) => {
                                  return compactNumber(value)
                              },
                          },
                },
            }
        } else if (type === 'horizontalBar') {
            options.scales = {
                x: {
                    min: 0,
                    precision: 0,
                    beginAtZero: true,
                    display: true,
                    ticks: {
                        ...tickOptions,
                        callback: (value) => {
                            return compactNumber(value)
                        },
                    },
                },
                y: {
                    min: 0,
                    precision: 0,
                    beginAtZero: true,
                    ticks: {
                        color: colors.axisLabel,
                    },
                },
            }
            options.indexAxis = 'y'
        } else if (type === 'doughnut') {
            options = {
                responsive: true,
                maintainAspectRatio: false,
                hover: {
                    mode: 'index',
                    onHover: options.hover.onHover,
                },
                plugins: {
                    crosshair: false,
                },
                onClick: options.onClick,
            }
        } else if (type === 'histogram') {
            options = {
                ...options,
                barPercentage: 1,
            }
        }

        console.log(
            'TYPE',
            ['histogram', 'horizontalBar'].includes(type),
            type,
            options,
            labels,
            datasets,
            ['histogram', 'horizontalBar'].includes(type) ? 'bar' : type
        )

        myLineChart.current = new Chart(myChartRef, {
            type: (['histogram', 'horizontalBar'].includes(type) ? 'bar' : type) as ChartType,
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
            {annotationsCondition &&
                renderAnnotations({
                    labeledDays: datasets[0].labels,
                    dates: datasets[0].days,
                    leftExtent,
                    interval: boundaryInterval,
                    topExtent,
                    dashboardItemId,
                    currentDateMarker:
                        focused || annotationsFocused
                            ? selectedDayLabel
                            : enabled
                            ? datasets[0].days[labelIndex]
                            : null,
                    onClick: () => {
                        setFocused(false)
                        setAnnotationsFocused(true)
                    },
                    onClose: () => setAnnotationsFocused(false),
                    graphColor: color,
                    color: colors.annotationColor,
                    accessoryColor: colors.annotationAccessoryColor,
                })}
            {annotationsCondition && !annotationsFocused && (enabled || focused) && left >= 0 && (
                <AnnotationMarker
                    dashboardItemId={dashboardItemId}
                    currentDateMarker={focused ? selectedDayLabel : datasets[0].days[labelIndex]}
                    onClick={() => {
                        setFocused(true)
                        setHoldLeft(left)
                        setHoldLabelIndex(labelIndex)
                        setSelectedDayLabel(datasets[0].days[labelIndex])
                    }}
                    getPopupContainer={() => annotationsRoot?.current}
                    onCreateAnnotation={(textInput, applyAll) => {
                        if (applyAll) {
                            createGlobalAnnotation(textInput, datasets[0].days[holdLabelIndex], dashboardItemId)
                        } else if (dashboardItemId) {
                            createAnnotationNow(textInput, datasets[0].days[holdLabelIndex])
                        } else {
                            createAnnotation(textInput, datasets[0].days[holdLabelIndex])
                            toast('This annotation will be saved if the graph is made into a dashboard item!')
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

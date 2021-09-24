import React, { useState, useEffect, useRef } from 'react'
import ReactDOM from 'react-dom'
import { useActions, useValues } from 'kea'
import Chart from '@posthog/chart.js'
import 'chartjs-adapter-dayjs'
import PropTypes from 'prop-types'
import { compactNumber, lightenDarkenColor } from '~/lib/utils'
import { getBarColorFromStatus, getChartColors, getGraphColors } from 'lib/colors'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { toast } from 'react-toastify'
import { Annotations, annotationsLogic, AnnotationMarker } from 'lib/components/Annotations'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import dayjs from 'dayjs'
import './LineGraph.scss'
import { InsightLabel } from 'lib/components/InsightLabel'
import { InsightTooltip } from '../InsightTooltip/InsightTooltip'

//--Chart Style Options--//
Chart.defaults.global.legend.display = false
Chart.defaults.global.animation.duration = 0
Chart.defaults.global.elements.line.tension = 0
//--Chart Style Options--//

const noop = () => {}

export function LineGraph({
    datasets,
    visibilityMap = null,
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
}) {
    const chartRef = useRef()
    const myLineChart = useRef()
    const annotationsRoot = useRef()
    const [left, setLeft] = useState(-1)
    const [holdLeft, setHoldLeft] = useState(0)
    const [enabled, setEnabled] = useState(false)
    const [focused, setFocused] = useState(false)
    const [annotationsFocused, setAnnotationsFocused] = useState(false)
    const [labelIndex, setLabelIndex] = useState(null)
    const [holdLabelIndex, setHoldLabelIndex] = useState(null)
    const [selectedDayLabel, setSelectedDayLabel] = useState(null)
    const { createAnnotation, createAnnotationNow, updateDiffType, createGlobalAnnotation } = !inSharedMode
        ? useActions(annotationsLogic({ pageKey: dashboardItemId || null }))
        : { createAnnotation: noop, createAnnotationNow: noop, updateDiffType: noop, createGlobalAnnotation: noop }

    const { annotationsList, annotationsLoading } = !inSharedMode
        ? useValues(annotationsLogic({ pageKey: dashboardItemId || null }))
        : { annotationsList: [], annotationsLoading: false }
    const [leftExtent, setLeftExtent] = useState(0)
    const [boundaryInterval, setBoundaryInterval] = useState(0)
    const [topExtent, setTopExtent] = useState(0)
    const [annotationInRange, setInRange] = useState(false)
    const [tooltipVisible, setTooltipVisible] = useState(false)
    const size = useWindowSize()

    const annotationsCondition =
        type === 'line' &&
        datasets?.length > 0 &&
        !datasets[0].compare &&
        !inSharedMode &&
        datasets[0].labels?.[0] !== '1 day' // stickiness graphs

    const colors = getGraphColors(color === 'white')

    useEscapeKey(() => setFocused(false), [focused])

    useEffect(() => {
        buildChart()
    }, [datasets, color, visibilityMap])

    // Hacky! - Chartjs doesn't internally call tooltip callback on mouseout from right border.
    // Let's manually remove tooltips when the chart is being hovered over. #5061
    useEffect(() => {
        const removeTooltip = () => {
            const tooltipEl = document.getElementById('ph-graph-tooltip')

            if (tooltipEl && !tooltipVisible) {
                tooltipEl.style.opacity = 0
            }
        }
        removeTooltip()
        return removeTooltip // remove tooltip on component unmount
    }, [tooltipVisible])

    // annotation related effects

    // update boundaries and axis padding when user hovers with mouse or annotations load
    useEffect(() => {
        if (annotationsCondition && myLineChart.current) {
            myLineChart.current.options.scales.xAxes[0].ticks.padding = annotationInRange || focused ? 35 : 0
            myLineChart.current.update()
            calculateBoundaries()
        }
    }, [annotationsLoading, annotationsCondition, annotationsList, annotationInRange])

    useEffect(() => {
        if (annotationsCondition && datasets[0]?.days?.length > 0) {
            const begin = dayjs(datasets[0].days[0])
            const end = dayjs(datasets[0].days[datasets[0].days.length - 1]).add(2, 'days')
            const checkBetween = (element) =>
                dayjs(element.date_marker).isSameOrBefore(end) && dayjs(element.date_marker).isSameOrAfter(begin)
            setInRange(annotationsList.some(checkBetween))
        }
    }, [datasets, annotationsList, annotationsCondition])

    // recalculate diff if interval type selection changes
    useEffect(() => {
        if (annotationsCondition) {
            updateDiffType(datasets[0].days)
        }
    }, [datasets, type, annotationsCondition])

    // update only boundaries when window size changes or chart type changes
    useEffect(() => {
        if (annotationsCondition) {
            calculateBoundaries()
        }
    }, [myLineChart.current, size, type, annotationsCondition])

    function calculateBoundaries() {
        const boundaryLeftExtent = myLineChart.current.scales['x-axis-0'].left
        const boundaryRightExtent = myLineChart.current.scales['x-axis-0'].right
        const boundaryTicks = myLineChart.current.scales['x-axis-0'].ticks.length
        const boundaryDelta = boundaryRightExtent - boundaryLeftExtent
        const _boundaryInterval = boundaryDelta / (boundaryTicks - 1)
        const boundaryTopExtent = myLineChart.current.scales['x-axis-0'].top + 8
        setLeftExtent(boundaryLeftExtent)
        setBoundaryInterval(_boundaryInterval)
        setTopExtent(boundaryTopExtent)
    }

    function processDataset(dataset, index) {
        const colorList = getChartColors(color || 'white')
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
            type,
        }
    }

    function buildChart() {
        const myChartRef = chartRef.current.getContext('2d')

        if (typeof myLineChart.current !== 'undefined') {
            myLineChart.current.destroy()
        }

        // if chart is line graph, make duplicate lines and overlay to show dotted lines
        const isLineGraph = type === 'line'
        if (isLineGraph) {
            datasets = [
                ...datasets.map((dataset, index) => {
                    let datasetCopy = Object.assign({}, dataset)
                    let data = [...(dataset.data || [])]
                    let _labels = [...(dataset.labels || [])]
                    let days = [...(dataset.days || [])]
                    data.pop()
                    _labels.pop()
                    days.pop()
                    datasetCopy.data = data
                    datasetCopy.labels = _labels
                    datasetCopy.days = days
                    return processDataset(datasetCopy, index)
                }),
                ...datasets.map((dataset, index) => {
                    let datasetCopy = Object.assign({}, dataset)
                    let datasetLength = datasetCopy.data?.length ?? 0
                    datasetCopy.dotted = true

                    // if last date is still active show dotted line
                    if (isInProgress) {
                        datasetCopy.borderDash = [10, 10]
                    }

                    datasetCopy.data =
                        datasetCopy.data?.length > 2
                            ? datasetCopy.data.map((datum, idx) =>
                                  idx === datasetLength - 1 || idx === datasetLength - 2 ? datum : null
                              )
                            : datasetCopy.data
                    return processDataset(datasetCopy, index)
                }),
            ]
            if (visibilityMap) {
                datasets = datasets.filter((data) => visibilityMap[data.id])
            }
        } else {
            datasets = datasets.map((dataset, index) => processDataset(dataset, index))
        }

        const tickOptions = {
            autoSkip: true,
            beginAtZero: true,
            min: 0,
            fontColor: colors.axisLabel,
            precision: 0,
        }

        const inspectPersonsLabel = !dashboardItemId && onClick && showPersonsModal

        const tooltipOptions = {
            enabled: false, // disable builtin tooltip (use custom markup)
            mode: 'nearest',
            // If bar, we want to only show the tooltip for what we're hovering over
            // to avoid confusion
            axis: type === 'horizontalBar' ? 'xy' : 'x',
            intersect: type === 'horizontalBar',
            itemSort: (a, b) => b.yLabel - a.yLabel,
            callbacks: {
                label: function labelElement(tooltipItem, data) {
                    const entityData = data.datasets[tooltipItem.datasetIndex]
                    if (entityData.dotted && !(tooltipItem.index === entityData.data.length - 1)) {
                        return null
                    }

                    const label = entityData.chartLabel || entityData.label || tooltipItem.label || ''
                    const action = entityData.action || (entityData.actions && entityData.actions[tooltipItem.index])

                    let value = tooltipItem.yLabel.toLocaleString()
                    const actionObjKey = type === 'horizontalBar' ? 'actions' : 'action'

                    if (type === 'horizontalBar') {
                        const perc = Math.round((tooltipItem.xLabel / totalValue) * 100, 2)
                        value = `${tooltipItem.xLabel.toLocaleString()} (${perc}%)`
                    }

                    let showCountedByTag = false
                    let numberOfSeries = 1
                    if (data.datasets.find((item) => item[actionObjKey])) {
                        // The above statement will always be true except in Sessions tab
                        showCountedByTag = !!data.datasets.find(
                            ({ [actionObjKey]: { math } }) => math && math !== 'total'
                        )
                        numberOfSeries = new Set(data.datasets.flatMap(({ [actionObjKey]: { order } }) => order)).size
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
                        />
                    )
                },
            },
            custom: function (tooltipModel) {
                let tooltipEl = document.getElementById('ph-graph-tooltip')
                // Create element on first render
                if (!tooltipEl) {
                    tooltipEl = document.createElement('div')
                    tooltipEl.id = 'ph-graph-tooltip'
                    tooltipEl.classList.add('ph-graph-tooltip')
                    document.body.appendChild(tooltipEl)
                }
                if (tooltipModel.opacity === 0) {
                    tooltipEl.style.opacity = 0
                    return
                }

                // Set caret position
                // Reference: https://www.chartjs.org/docs/master/configuration/tooltip.html
                tooltipEl.classList.remove('above', 'below', 'no-transform')
                tooltipEl.classList.add(tooltipModel.yAlign || 'no-transform')
                const bounds = chartRef.current.getBoundingClientRect()
                const chartClientLeft = bounds.left + window.pageXOffset

                tooltipEl.style.opacity = 1
                tooltipEl.style.position = 'absolute'
                tooltipEl.style.padding = tooltipModel.padding + 'px'
                tooltipEl.style.pointerEvents = 'none'

                if (tooltipModel.body) {
                    const referenceDataPoint = tooltipModel.dataPoints[0] // Use this point as reference to get the date
                    const dataset = datasets[referenceDataPoint.datasetIndex]

                    const altTitle =
                        tooltipModel.title && (dataset.compare || tooltipPreferAltTitle) ? tooltipModel.title[0] : '' // When comparing we show the whole range for clarity; when on stickiness we show the relative timeframe (e.g. `5 days`)
                    const referenceDate = !dataset.compare ? dataset.days[referenceDataPoint.index] : undefined
                    const bodyLines = tooltipModel.body
                        .flatMap(({ lines }) => lines)
                        .map((component, idx) => ({
                            id: idx,
                            component,
                        }))

                    ReactDOM.render(
                        <InsightTooltip
                            altTitle={altTitle}
                            referenceDate={referenceDate}
                            interval={interval}
                            bodyLines={bodyLines}
                            inspectPersonsLabel={inspectPersonsLabel}
                            preferAltTitle={tooltipPreferAltTitle}
                            hideHeader={type === 'horizontalBar'}
                        />,
                        tooltipEl
                    )
                }

                const horizontalBarTopOffset =
                    type === 'horizontalBar' ? tooltipModel.caretY - tooltipEl.clientHeight / 2 : 0
                const tooltipClientTop = bounds.top + window.pageYOffset + horizontalBarTopOffset

                const defaultOffsetLeft = Math.max(chartClientLeft, chartClientLeft + tooltipModel.caretX + 8)
                const maxXPosition = bounds.right - tooltipEl.clientWidth
                const tooltipClientLeft =
                    defaultOffsetLeft > maxXPosition
                        ? chartClientLeft + tooltipModel.caretX - tooltipEl.clientWidth - 8 // If tooltip is too large (or close to the edge), show it to the left of the data point instead
                        : defaultOffsetLeft

                tooltipEl.style.top = tooltipClientTop + 'px'
                tooltipEl.style.left = tooltipClientLeft + 'px'
            },
        }

        let options = {
            responsive: true,
            maintainAspectRatio: false,
            scaleShowHorizontalLines: false,
            tooltips: tooltipOptions,
            plugins:
                type !== 'horizontalBar' && !datasets?.[0]?.status
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
                      },
            hover: {
                mode: 'nearestX',
                axis: 'xy',
                intersect: false,
                onHover(evt) {
                    if (onClick) {
                        const point = this.getElementAtEvent(evt)
                        if (point.length) {
                            evt.target.style.cursor = 'pointer'
                        } else {
                            evt.target.style.cursor = 'default'
                        }
                    }
                    if (evt.type === 'mouseout') {
                        setTooltipVisible(false)
                    } else {
                        setTooltipVisible(true)
                    }
                },
            },
            onClick: (_, [point]) => {
                if (point && onClick) {
                    const dataset = datasets[point._datasetIndex]
                    onClick({
                        point,
                        dataset,
                        index: point._index,
                        label:
                            typeof point._index !== 'undefined' && dataset.labels
                                ? dataset.labels[point._index]
                                : undefined,
                        day:
                            typeof point._index !== 'undefined' && dataset.days
                                ? dataset['compare']
                                    ? dataset.dates[point._index]
                                    : dataset.days[point._index]
                                : undefined,
                        value:
                            typeof point._index !== 'undefined' && dataset.data
                                ? dataset.data[point._index]
                                : undefined,
                    })
                }
            },
        }

        if (type === 'bar') {
            options.scales = {
                xAxes: [{ stacked: true, ticks: { fontColor: colors.axisLabel } }],
                yAxes: [
                    {
                        stacked: true,
                        ticks: {
                            fontColor: colors.axisLabel,
                            callback: (value) => {
                                return compactNumber(value)
                            },
                        },
                    },
                ],
            }
        } else if (type === 'line') {
            options.scales = {
                xAxes: [
                    {
                        display: true,
                        gridLines: { lineWidth: 0, color: colors.axisLine, zeroLineColor: colors.axis },
                        ticks: {
                            ...tickOptions,
                            padding: annotationsLoading || !annotationInRange ? 0 : 35,
                        },
                    },
                ],
                yAxes: [
                    {
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
                ],
            }
        } else if (type === 'horizontalBar') {
            options.scales = {
                xAxes: [
                    {
                        display: true,
                        ticks: {
                            ...tickOptions,
                            callback: (value) => {
                                return compactNumber(value)
                            },
                        },
                    },
                ],
                yAxes: [
                    {
                        ticks: { fontColor: colors.axisLabel },
                    },
                ],
            }
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

        myLineChart.current = new Chart(myChartRef, {
            type: type === 'histogram' ? 'bar' : type,
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

                    const xAxis = myLineChart.current.scales['x-axis-0'],
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
                    labeledDays={datasets[0].labels}
                    dates={datasets[0].days}
                    leftExtent={leftExtent}
                    interval={boundaryInterval}
                    topExtent={topExtent}
                    dashboardItemId={dashboardItemId}
                    currentDateMarker={
                        focused || annotationsFocused ? selectedDayLabel : enabled ? datasets[0].days[labelIndex] : null
                    }
                    onClick={() => {
                        setFocused(false)
                        setAnnotationsFocused(true)
                    }}
                    onClose={() => setAnnotationsFocused(false)}
                    graphColor={color}
                    color={colors.annotationColor}
                    accessoryColor={colors.annotationAccessoryColor}
                />
            )}
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

const mapRange = (value, x1, y1, x2, y2) => Math.floor(((value - x1) * (y2 - x2)) / (y1 - x1) + x2)

LineGraph.propTypes = {
    datasets: PropTypes.arrayOf(PropTypes.shape({ label: PropTypes.string, count: PropTypes.number })).isRequired,
    labels: PropTypes.array.isRequired,
    options: PropTypes.object,
    type: PropTypes.string,
    onClick: PropTypes.func,
    totalValue: PropTypes.number,
    isInProgress: PropTypes.bool,
    inSharedMode: PropTypes.bool,
    percentage: PropTypes.bool,
}

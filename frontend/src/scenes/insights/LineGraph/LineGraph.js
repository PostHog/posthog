import React, { useState, useEffect, useRef } from 'react'
import ReactDOM from 'react-dom'
import { useActions, useValues } from 'kea'
import Chart from 'chart.js'
import 'chartjs-adapter-dayjs'
import PropTypes from 'prop-types'
import { formatLabel, maybeAddCommasToInteger } from '~/lib/utils'
import { getBarColorFromStatus, getChartColors } from 'lib/colors'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { toast } from 'react-toastify'
import { Annotations, annotationsLogic, AnnotationMarker } from 'lib/components/Annotations'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import dayjs from 'dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import './LineGraph.scss'
import 'chartjs-plugin-crosshair'
import { InsightLabel } from 'lib/components/InsightLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { InsightTooltip } from '../InsightTooltip'

//--Chart Style Options--//
// Chart.defaults.global.defaultFontFamily = "'PT Sans', sans-serif"
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
    dashboardItemId,
    inSharedMode,
    percentage = false,
    totalValue,
}) {
    const chartRef = useRef()
    const myLineChart = useRef()
    const { featureFlags } = useValues(featureFlagLogic)
    const newUI = featureFlags[FEATURE_FLAGS.NEW_TOOLTIPS]
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
    const [interval, setInterval] = useState(0)
    const [topExtent, setTopExtent] = useState(0)
    const [annotationInRange, setInRange] = useState(false)
    const size = useWindowSize()

    const annotationsCondition =
        type === 'line' &&
        datasets.length > 0 &&
        !datasets[0].compare &&
        !inSharedMode &&
        datasets[0].labels[0] !== '1 day' // stickiness graphs

    const colors = {
        axisLabel: color === 'white' ? '#333' : 'rgba(255,255,255,0.8)',
        axisLine: color === 'white' ? '#ddd' : 'rgba(255,255,255,0.2)',
        axis: color === 'white' ? '#999' : 'rgba(255,255,255,0.6)',
        crosshair: 'rgba(0,0,0,0.2)',
        tooltipBackground: '#1dc9b7',
        tooltipTitle: '#fff',
        tooltipBody: '#fff',
        annotationColor: color === 'white' ? null : 'white',
        annotationAccessoryColor: color === 'white' ? null : 'black',
    }

    useEscapeKey(() => setFocused(false), [focused])

    useEffect(() => {
        buildChart()
    }, [datasets, color, visibilityMap])

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
        const boundaryInterval = boundaryDelta / (boundaryTicks - 1)
        const boundaryTopExtent = myLineChart.current.scales['x-axis-0'].top + 8
        setLeftExtent(boundaryLeftExtent)
        setInterval(boundaryInterval)
        setTopExtent(boundaryTopExtent)
    }

    function processDataset(dataset, index) {
        const colorList = getChartColors(color || 'white')
        const borderColor = dataset?.status
            ? getBarColorFromStatus(dataset.status)
            : colorList[index % colorList.length]
        const hoverColor = dataset?.status ? getBarColorFromStatus(dataset.status, true) : undefined

        return {
            borderColor,
            hoverBorderColor: hoverColor,
            hoverBackgroundColor: hoverColor,
            backgroundColor: (type === 'bar' || type === 'doughnut') && borderColor,
            fill: false,
            borderWidth: newUI ? 2 : 1,
            pointRadius: newUI ? 0 : undefined,
            pointHitRadius: 8,
            ...dataset,
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
                    let data = [...dataset.data]
                    let _labels = [...dataset.labels]
                    let days = [...dataset.days]
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
                    let datasetLength = datasetCopy.data.length
                    datasetCopy.dotted = true

                    // if last date is still active show dotted line
                    if (isInProgress) {
                        datasetCopy.borderDash = [10, 10]
                    }

                    datasetCopy.data =
                        datasetCopy.data.length > 2
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

        const inspectUsersLabel = !dashboardItemId && onClick

        const newUITooltipOptions = {
            enabled: false, // disable builtin tooltip (use custom markup)
            mode: 'nearest',
            axis: 'x',
            intersect: false,
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

                    const showCountedByTag = !!data.datasets.find(
                        ({ [actionObjKey]: { math } }) => math && math !== 'total'
                    )

                    return (
                        <InsightLabel
                            propertyValue={label}
                            action={action}
                            value={value}
                            showCountedByTag={showCountedByTag}
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
                const chartClientTop = bounds.top + window.pageYOffset
                const tooltipCaretOffsetLeft = Math.max(chartClientLeft, chartClientLeft + tooltipModel.caretX - 50)
                const maxXPosition = bounds.right - 150 // ensure the tooltip doesn't exceed the bounds of the window
                tooltipEl.style.opacity = 1
                tooltipEl.style.position = 'absolute'
                tooltipEl.style.left = Math.min(tooltipCaretOffsetLeft, maxXPosition) + 'px'
                tooltipEl.style.top = chartClientTop + 'px'
                tooltipEl.style.padding = tooltipModel.padding + 'px'
                tooltipEl.style.pointerEvents = 'none'
                if (tooltipModel.body) {
                    const titleLines = tooltipModel.title || []
                    const bodyLines = tooltipModel.body
                        .flatMap(({ lines }) => lines)
                        .map((component, idx) => ({
                            id: idx,
                            component,
                            ...tooltipModel.labelColors[idx],
                        }))
                    ReactDOM.render(
                        <InsightTooltip
                            titleLines={titleLines}
                            bodyLines={bodyLines}
                            inspectUsersLabel={inspectUsersLabel}
                        />,
                        tooltipEl
                    )
                }
            },
        }

        const tooltipOptions = newUI
            ? newUITooltipOptions
            : {
                  enabled: true,
                  intersect: false,
                  mode: 'nearest',
                  // If bar, we want to only show the tooltip for what we're hovering over
                  // to avoid confusion
                  axis: { bar: 'x', horizontalBar: 'y' }[type],
                  bodySpacing: 5,
                  position: 'nearest',
                  yPadding: 10,
                  xPadding: 10,
                  caretPadding: 0,
                  displayColors: false,
                  backgroundColor: colors.tooltipBackground,
                  titleFontColor: colors.tooltipTitle,
                  bodyFontColor: colors.tooltipBody,
                  footerFontColor: colors.tooltipBody,
                  borderColor: colors.tooltipBorder,
                  labelFontSize: 23,
                  cornerRadius: 4,
                  fontSize: 12,
                  footerSpacing: 0,
                  titleSpacing: 0,
                  footerFontStyle: 'italic',
                  callbacks: {
                      label: function (tooltipItem, data) {
                          let entityData = data.datasets[tooltipItem.datasetIndex]
                          if (entityData.dotted && !(tooltipItem.index === entityData.data.length - 1)) {
                              return null
                          }
                          const label = entityData.chartLabel || entityData.label || tooltipItem.label || ''
                          const action =
                              entityData.action || (entityData.actions && entityData.actions[tooltipItem.index])
                          const formattedLabel = action ? formatLabel(label, action) : label

                          let value = tooltipItem.yLabel.toLocaleString()
                          if (type === 'horizontalBar') {
                              const perc = Math.round((tooltipItem.xLabel / totalValue) * 100, 2)
                              value = `${tooltipItem.xLabel.toLocaleString()} (${perc}%)`
                          }
                          return (formattedLabel ? formattedLabel + ' — ' : '') + value + (percentage ? '%' : '')
                      },
                      footer: () => (inspectUsersLabel ? 'Click to see users related to the datapoint' : ''),
                  },
                  itemSort: (a, b) => b.yLabel - a.yLabel,
              }

        let options = {
            responsive: true,
            maintainAspectRatio: false,
            scaleShowHorizontalLines: false,
            tooltips: tooltipOptions,
            plugins: newUI
                ? {
                      crosshair: {
                          snapping: {
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
                mode: 'nearest',
                axis: newUI ? 'x' : 'xy',
                intersect: newUI ? false : true,
                onHover(evt) {
                    if (onClick) {
                        const point = this.getElementAtEvent(evt)
                        if (point.length) {
                            evt.target.style.cursor = 'pointer'
                        } else {
                            evt.target.style.cursor = 'default'
                        }
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
                                return maybeAddCommasToInteger(value)
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
                                      return value.toFixed(0) + '%' // convert it to percentage
                                  },
                              }
                            : {
                                  ...tickOptions,
                                  callback: (value) => {
                                      return maybeAddCommasToInteger(value)
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
                                return maybeAddCommasToInteger(value)
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
        }

        myLineChart.current = new Chart(myChartRef, {
            type,
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
                    interval={interval}
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

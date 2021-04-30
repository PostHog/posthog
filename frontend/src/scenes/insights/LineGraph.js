import React, { useState, useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import Chart from 'chart.js'
import 'chartjs-adapter-dayjs'
import PropTypes from 'prop-types'
import { formatLabel } from '~/lib/utils'
import { getBarColorFromStatus, getChartColors } from 'lib/colors'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { toast } from 'react-toastify'
import { Annotations, annotationsLogic, AnnotationMarker } from 'lib/components/Annotations'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import dayjs from 'dayjs'
import './Insights.scss'

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
    const [left, setLeft] = useState(0)
    const [holdLeft, setHoldLeft] = useState(0)
    const [enabled, setEnabled] = useState(false)
    const [focused, setFocused] = useState(false)
    const [annotationsFocused, setAnnotationsFocused] = useState(false)
    const [labelIndex, setLabelIndex] = useState(null)
    const [holdLabelIndex, setHoldLabelIndex] = useState(null)
    const [selectedDayLabel, setSelectedDayLabel] = useState(null)
    const { createAnnotation, createAnnotationNow, updateDiffType, createGlobalAnnotation } = !inSharedMode
        ? useActions(annotationsLogic({ pageKey: dashboardItemId ? dashboardItemId : null }))
        : { createAnnotation: noop, createAnnotationNow: noop, updateDiffType: noop, createGlobalAnnotation: noop }

    const { annotationsList, annotationsLoading } = !inSharedMode
        ? useValues(annotationsLogic({ pageKey: dashboardItemId ? dashboardItemId : null }))
        : { annotationsList: [], annotationsLoading: false }
    const [leftExtent, setLeftExtent] = useState(0)
    const [interval, setInterval] = useState(0)
    const [topExtent, setTopExtent] = useState(0)
    const [annotationInRange, setInRange] = useState(false)
    const size = useWindowSize()

    const annotationsCondition = type === 'line' && datasets.length > 0 && !datasets[0].compare && !inSharedMode

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
        const leftExtent = myLineChart.current.scales['x-axis-0'].left
        const rightExtent = myLineChart.current.scales['x-axis-0'].right
        const ticks = myLineChart.current.scales['x-axis-0'].ticks.length
        const delta = rightExtent - leftExtent
        const interval = delta / (ticks - 1)
        const topExtent = myLineChart.current.scales['x-axis-0'].top + 8
        setLeftExtent(leftExtent)
        setInterval(interval)
        setTopExtent(topExtent)
    }

    function processDataset(dataset, index) {
        const colorList = getChartColors(color || 'white')
        const borderColor = dataset?.status
            ? getBarColorFromStatus(dataset.status)
            : colorList[index % colorList.length]

        return {
            borderColor,
            backgroundColor: (type === 'bar' || type === 'doughnut') && borderColor,
            fill: false,
            borderWidth: 1,
            pointHitRadius: 8,
            ...dataset,
        }
    }

    function buildChart() {
        const myChartRef = chartRef.current.getContext('2d')

        const axisLabelColor = color === 'white' ? '#333' : 'rgba(255,255,255,0.8)'
        const axisLineColor = color === 'white' ? '#ddd' : 'rgba(255,255,255,0.2)'
        const axisColor = color === 'white' ? '#999' : 'rgba(255,255,255,0.6)'

        if (typeof myLineChart.current !== 'undefined') {
            myLineChart.current.destroy()
        }
        // if chart is line graph, make duplicate lines and overlay to show dotted lines
        const isLineGraph = type === 'line'
        datasets = isLineGraph
            ? [
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
            : datasets.map((dataset, index) => processDataset(dataset, index))

        if (isLineGraph && visibilityMap) {
            datasets = datasets.filter((data) => visibilityMap[data.id])
        }

        let options = {
            responsive: true,
            maintainAspectRatio: false,
            scaleShowHorizontalLines: false,
            tooltips: {
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
                backgroundColor: '#1dc9b7',
                titleFontColor: '#ffffff',
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
                    footer: () => (dashboardItemId || !onClick ? '' : 'Click to see users related to the datapoint'),
                },
                itemSort: (a, b) => b.yLabel - a.yLabel,
            },
            hover: {
                mode: 'nearest',
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
                xAxes: [{ stacked: true, ticks: { fontColor: axisLabelColor } }],
                yAxes: [{ stacked: true, ticks: { fontColor: axisLabelColor } }],
            }
        } else if (type === 'line') {
            options.scales = {
                xAxes: [
                    {
                        display: true,
                        gridLines: { lineWidth: 0, color: axisLineColor, zeroLineColor: axisColor },
                        ticks: {
                            autoSkip: true,
                            beginAtZero: true,
                            min: 0,
                            fontColor: axisLabelColor,
                            precision: 0,
                            padding: annotationsLoading || !annotationInRange ? 0 : 35,
                        },
                    },
                ],
                yAxes: [
                    {
                        display: true,
                        gridLines: { color: axisLineColor, zeroLineColor: axisColor },
                        ticks: percentage
                            ? {
                                  callback: function (value) {
                                      return value.toFixed(0) + '%' // convert it to percentage
                                  },
                              }
                            : {
                                  autoSkip: true,
                                  beginAtZero: true,
                                  min: 0,
                                  fontColor: axisLabelColor,
                                  precision: 0,
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
                            autoSkip: true,
                            beginAtZero: true,
                            min: 0,
                            fontColor: axisLabelColor,
                            precision: 0,
                        },
                    },
                ],
                yAxes: [
                    {
                        ticks: { fontColor: axisLabelColor },
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
                    var rect = e.currentTarget.getBoundingClientRect(),
                        offsetX = e.clientX - rect.left,
                        offsetY = e.clientY - rect.top
                    if (offsetY < topExtent - 30 && !focused && !annotationsFocused) {
                        setEnabled(false)
                        setLeft(-1)
                        return
                    }

                    const _leftExtent = myLineChart.current.scales['x-axis-0'].left
                    const _rightExtent = myLineChart.current.scales['x-axis-0'].right
                    const ticks = myLineChart.current.scales['x-axis-0'].ticks.length
                    const delta = _rightExtent - _leftExtent
                    const _interval = delta / (ticks - 1)
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
                    onClose={() => {
                        setAnnotationsFocused(false)
                    }}
                    graphColor={color}
                    color={color === 'white' ? null : 'white'}
                    accessoryColor={color === 'white' ? null : 'black'}
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
                    onCancelAnnotation={() => [setFocused(false)]}
                    onClose={() => setFocused(false)}
                    dynamic={true}
                    left={(focused ? holdLeft : left) - 12.5}
                    top={topExtent}
                    label={'Add Note'}
                    color={color === 'white' ? null : 'white'}
                    graphColor={color}
                    accessoryColor={color === 'white' ? null : 'black'}
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

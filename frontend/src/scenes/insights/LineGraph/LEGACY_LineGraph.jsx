import React, { useState, useEffect, useRef } from 'react'
import ReactDOM from 'react-dom'
import { Provider } from 'react-redux'
import { getContext, useActions, useValues } from 'kea'
import Chart from '@posthog/chart.js'
import 'chartjs-adapter-dayjs'
import PropTypes from 'prop-types'
import { areObjectValuesEmpty, capitalizeFirstLetter, compactNumber, lightenDarkenColor } from '~/lib/utils'
import { getBarColorFromStatus, getChartColors, getGraphColors } from 'lib/colors'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { Annotations, annotationsLogic, AnnotationMarker } from 'lib/components/Annotations'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import './LineGraph.scss'
import { InsightLabel } from 'lib/components/InsightLabel'
import { LEGACY_InsightTooltip } from '../InsightTooltip/LEGACY_InsightTooltip'
import { dayjs } from 'lib/dayjs'

//--Chart Style Options--//
Chart.defaults.global.legend.display = false
Chart.defaults.global.animation.duration = 0
Chart.defaults.global.elements.line.tension = 0
//--Chart Style Options--//

const noop = () => {}

export function LEGACY_LineGraph({
    datasets: _datasets,
    hiddenLegendKeys,
    labels,
    color,
    type,
    isInProgress = false,
    onClick,
    ['data-attr']: dataAttr,
    insightId,
    inSharedMode,
    percentage = false,
    interval = undefined,
    totalValue,
    showPersonsModal = true,
    tooltipPreferAltTitle = false,
    isCompare = false,
    incompletenessOffsetFromEnd = -1, // Number of data points at end of dataset to replace with a dotted line. Only used in line graphs.
}) {
    let datasets = _datasets
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
    const [tooltipVisible, setTooltipVisible] = useState(false)
    const size = useWindowSize()

    const annotationsCondition =
        type === 'line' && datasets?.length > 0 && !inSharedMode && datasets[0].labels?.[0] !== '1 day' // stickiness graphs

    const colors = getGraphColors(color === 'white')

    useEscapeKey(() => setFocused(false), [focused])

    useEffect(() => {
        buildChart()
    }, [datasets, color, hiddenLegendKeys])

    // Hacky! - Chartjs doesn't internally call tooltip callback on mouseout from right border.
    // Let's manually remove tooltips when the chart is being hovered over. #5061
    useEffect(() => {
        const removeTooltip = () => {
            const tooltipEl = document.getElementById('legacy-ph-graph-tooltip')

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
        if (annotationsCondition && datasets?.[0]?.days?.length > 0) {
            const begin = dayjs(datasets[0].days[0])
            const end = dayjs(datasets[0].days[datasets[0].days.length - 1]).add(2, 'days')
            const checkBetween = (element) =>
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

    function processDataset(dataset) {
        const colorList = getChartColors(color || 'white', _datasets.length, isCompare)
        const mainColor = dataset?.status
            ? getBarColorFromStatus(dataset.status)
            : colorList[(dataset.id ?? 0) % (_datasets?.length ?? 1)]
        const hoverColor = dataset?.status ? getBarColorFromStatus(dataset.status, true) : mainColor

        // `horizontalBar` colors are set in `ActionsHorizontalBar.tsx` and overriden in spread of `dataset` below
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

        // Hide intentionally hidden keys
        if (!areObjectValuesEmpty(hiddenLegendKeys)) {
            if (type === 'horizontalBar') {
                // If series are nested (for ActionsHorizontalBar only), filter out the series by index
                const filterFn = (_, i) => !hiddenLegendKeys?.[i]
                datasets = datasets.map((_data) => {
                    // Performs a filter transformation on properties that contain arrayed data
                    return Object.fromEntries(
                        Object.entries(_data).map(([key, val]) =>
                            Array.isArray(val) && val.length === datasets?.[0]?.actions?.length
                                ? [key, val?.filter(filterFn)]
                                : [key, val]
                        )
                    )
                })
            } else {
                datasets = datasets.filter((data) => !hiddenLegendKeys?.[data.id])
            }
        }

        // if chart is line graph, make duplicate lines and overlay to show dotted lines
        const isLineGraph = type === 'line'
        if (isLineGraph) {
            datasets = [
                ...datasets.map((dataset, index) => {
                    let datasetCopy = Object.assign({}, dataset)
                    const sliceTo = incompletenessOffsetFromEnd || (datasetCopy.data?.length ?? 0)
                    const data = [...(dataset.data || [])].slice(0, sliceTo)
                    const _labels = [...(dataset.labels || [])].slice(0, sliceTo)
                    const days = [...(dataset.days || [])].slice(0, sliceTo)
                    datasetCopy.data = data
                    datasetCopy.labels = _labels
                    datasetCopy.days = days
                    return processDataset(datasetCopy, index)
                }),
                ...datasets.map((dataset, index) => {
                    let datasetCopy = Object.assign({}, dataset)
                    datasetCopy.dotted = true

                    // if last date is still active show dotted line
                    if (isInProgress) {
                        datasetCopy.borderDash = [10, 10]
                    }

                    // Nullify dates that don't have dotted line
                    const sliceFrom = incompletenessOffsetFromEnd - 1 || (datasetCopy.data?.length ?? 0)
                    datasetCopy.data =
                        datasetCopy.data?.length === 1 && !isInProgress
                            ? []
                            : (datasetCopy.data?.slice(0, sliceFrom).map(() => null) ?? []).concat(
                                  datasetCopy.data?.slice(sliceFrom) ?? []
                              )

                    return processDataset(datasetCopy, index)
                }),
            ]
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

                    const label = entityData.label || tooltipItem.label || ''
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
                            compareValue={
                                entityData.compare_label ? capitalizeFirstLetter(entityData.compare_label) : undefined
                            }
                            seriesStatus={entityData.status}
                            pillMidEllipsis={entityData?.filter?.breakdown === '$current_url'}
                        />
                    )
                },
            },
            custom: function (tooltipModel) {
                let tooltipEl = document.getElementById('legacy-ph-graph-tooltip')
                // Create element on first render
                if (!tooltipEl) {
                    tooltipEl = document.createElement('div')
                    tooltipEl.id = 'legacy-ph-graph-tooltip'
                    tooltipEl.classList.add('legacy-ph-graph-tooltip')
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
                    const seriesData = tooltipModel.body
                        .flatMap(({ lines }) => lines)
                        .map((component, idx) => ({
                            id: idx,
                            component,
                        }))

                    ReactDOM.render(
                        <Provider store={getContext().store}>
                            <LEGACY_InsightTooltip
                                altTitle={altTitle}
                                referenceDate={referenceDate}
                                interval={interval}
                                bodyLines={seriesData}
                                inspectPersonsLabel={onClick && showPersonsModal}
                                preferAltTitle={tooltipPreferAltTitle}
                                hideHeader={type === 'horizontalBar'}
                            />
                        </Provider>,
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
                    const point = this.getElementAtEvent(evt)
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
            onClick: (_, [point]) => {
                if (point && onClick) {
                    const dataset = datasets[point._datasetIndex]
                    // Makes onClick forward compatible with new LineGraph typing
                    onClick({
                        points: {
                            pointsIntersectingLine: [{ ...point, dataset }],
                            pointsIntersectingClick: [{ ...point, dataset }],
                            clickedPointNotLine: true,
                            referencePoint: { ...point, dataset },
                        },
                        index: point._index,
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
                        ticks: {
                            fontColor: colors.axisLabel,
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
                    insightId={insightId}
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
                    color={colors.annotationColor}
                    accessoryColor={colors.annotationAccessoryColor}
                />
            )}
            {annotationsCondition && !annotationsFocused && (enabled || focused) && left >= 0 && (
                <AnnotationMarker
                    insightId={insightId}
                    currentDateMarker={focused ? selectedDayLabel : datasets[0].days[labelIndex]}
                    onClick={() => {
                        setFocused(true)
                        setHoldLeft(left)
                        setHoldLabelIndex(labelIndex)
                        setSelectedDayLabel(datasets[0].days[labelIndex])
                    }}
                    getPopupContainer={() => annotationsRoot?.current}
                    onCreateAnnotation={(textInput, applyAll) => {
                        const date = datasets?.[0]?.days?.[holdLabelIndex]
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

const mapRange = (value, x1, y1, x2, y2) => Math.floor(((value - x1) * (y2 - x2)) / (y1 - x1) + x2)

LEGACY_LineGraph.propTypes = {
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

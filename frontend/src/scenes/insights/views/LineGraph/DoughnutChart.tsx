import React, { useEffect, useRef } from 'react'
import {
    registerables,
    ActiveElement,
    Chart,
    ChartDataset,
    ChartEvent,
    ChartItem,
    ChartType,
    InteractionItem,
    ChartPluginsOptions,
    PluginOptionsByType,
    ChartTypeRegistry,
} from 'chart.js'
import 'chartjs-adapter-dayjs'
import { areObjectValuesEmpty, lightenDarkenColor } from '~/lib/utils'
import { getBarColorFromStatus, getSeriesColor } from 'lib/colors'
import { GraphDataset, GraphPoint, GraphType } from '~/types'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { LineGraphProps } from 'scenes/insights/views/LineGraph/LineGraph'
import CrosshairPlugin, { CrosshairOptions } from 'chartjs-plugin-crosshair'
import { _DeepPartialObject } from 'chart.js/types/utils'

if (registerables) {
    // required for storybook to work, not found in esbuild
    Chart.register(...registerables)
}
Chart.register(CrosshairPlugin)
Chart.defaults.animation['duration'] = 0

export function DoughnutChart({
    datasets: _datasets,
    hiddenLegendKeys,
    labels,
    type,
    onClick,
    ['data-attr']: dataAttr,
    isCompare = false,
    aggregationAxisFormat = 'numeric',
}: LineGraphProps): JSX.Element {
    const isPie = type === GraphType.Pie

    if (!isPie) {
        throw new Error('PieChart must be a pie chart')
    }

    let datasets = _datasets

    const canvasRef = useRef<HTMLCanvasElement | null>(null)

    const isBackgroundBasedGraphType = true

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

        return {
            borderColor: mainColor,
            hoverBorderColor: isBackgroundBasedGraphType ? lightenDarkenColor(mainColor, -20) : hoverColor,
            hoverBackgroundColor: isBackgroundBasedGraphType ? lightenDarkenColor(mainColor, -20) : undefined,
            backgroundColor: isBackgroundBasedGraphType ? mainColor : undefined,
            fill: false,
            borderWidth: 2,
            pointRadius: 0,
            hitRadius: 0,
            order: 1,
            ...(type === GraphType.Histogram ? { barPercentage: 1 } : {}),
            ...dataset,
            hoverBorderWidth: 2,
            hoverBorderRadius: 2,
            type: type as ChartType,
        }
    }

    // Build chart
    useEffect(() => {
        // Hide intentionally hidden keys
        if (!areObjectValuesEmpty(hiddenLegendKeys)) {
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
        }

        datasets = datasets.map((dataset) => processDataset(dataset))

        const newChart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
            type: type as ChartType,
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                hover: {
                    mode: 'index',
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
                },
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
                } as _DeepPartialObject<PluginOptionsByType<keyof ChartTypeRegistry>> & ChartPluginsOptions,
            },
        })
        return () => newChart.destroy()
    }, [datasets, hiddenLegendKeys])

    return (
        <div className="LineGraph absolute w-full h-full" data-attr={dataAttr}>
            <canvas ref={canvasRef} />
        </div>
    )
}

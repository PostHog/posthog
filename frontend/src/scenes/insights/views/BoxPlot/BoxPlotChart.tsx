import { useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import 'scenes/insights/InsightTooltip/InsightTooltip.scss'
import { Chart, ChartConfiguration, ChartEvent } from 'lib/Chart'
import { getGraphColors, getSeriesColor } from 'lib/colors'
import { DateDisplay } from 'lib/components/DateDisplay'
import { useChart } from 'lib/hooks/useChart'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { useInsightTooltip } from 'scenes/insights/useInsightTooltip'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { BoxPlotDatum, InsightActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import { ChartParams } from '~/types'

import { boxPlotChartLogic } from './boxPlotChartLogic'

const BOX_PLOT_STATS = ['Max', '75th percentile', 'Median', 'Mean', '25th percentile', 'Min'] as const

function boxPlotDatumToSeriesData(data: BoxPlotDatum): SeriesDatum[] {
    const values = [data.max, data.p75, data.median, data.mean, data.p25, data.min]
    return BOX_PLOT_STATS.map((stat, idx) => ({
        id: idx,
        dataIndex: 0,
        datasetIndex: 0,
        label: stat,
        order: idx,
        color: getSeriesColor(0),
        count: values[idx],
    }))
}

function getNearestDataIndex(chart: Chart, event: ChartEvent | { x: number; y: number }): number | null {
    const xScale = chart.scales.x
    if (!xScale || event.x == null) {
        return null
    }
    const labels = xScale.ticks
    if (!labels || labels.length === 0) {
        return null
    }

    let closestIndex = 0
    let closestDistance = Infinity
    for (let i = 0; i < labels.length; i++) {
        const tickX = xScale.getPixelForTick(i)
        const distance = Math.abs(event.x - tickX)
        if (distance < closestDistance) {
            closestDistance = distance
            closestIndex = i
        }
    }
    return closestIndex
}

export function BoxPlotChart({ showPersonsModal = true }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { boxplotData, chartData, labels, yAxisScaleType, querySource, interval, insightData, trendsFilter } =
        useValues(boxPlotChartLogic(insightProps))
    const { timezone, weekStartDay } = useValues(teamLogic)

    const colors = getGraphColors()
    const seriesColor = getSeriesColor(0)

    const { getTooltip, hideTooltip, positionTooltip } = useInsightTooltip()
    const activeIndexRef = useRef<number | null>(null)

    const showTooltipForIndex = useCallback(
        (chart: Chart, dataIndex: number, caretX: number, caretY: number) => {
            if (!boxplotData?.[dataIndex]) {
                return
            }
            const [tooltipRoot, tooltipEl] = getTooltip()
            tooltipEl.classList.remove('above', 'below', 'no-transform', 'opacity-0', 'invisible')
            tooltipEl.classList.add('no-transform')
            tooltipEl.style.opacity = '1'

            const datum = boxplotData[dataIndex]
            const seriesData = boxPlotDatumToSeriesData(datum)

            tooltipRoot.render(
                <InsightTooltip
                    date={datum.day}
                    timezone={timezone}
                    seriesData={seriesData}
                    interval={interval}
                    dateRange={insightData?.resolved_date_range}
                    hideColorCol
                    renderSeries={(value) => <div className="datum-label-column">{value}</div>}
                    renderCount={(value: number) => formatAggregationAxisValue(trendsFilter, value)}
                    hideInspectActorsSection={!showPersonsModal}
                    groupTypeLabel="people"
                />
            )

            const bounds = chart.canvas.getBoundingClientRect()
            positionTooltip(tooltipEl, bounds, caretX, caretY, true)
        },
        [boxplotData, getTooltip, positionTooltip, timezone, interval, insightData, showPersonsModal, trendsFilter]
    )

    const handleClick = useCallback(
        (chart: Chart, event: ChartEvent) => {
            if (!showPersonsModal || !querySource || event.x == null) {
                return
            }
            const dataIndex = getNearestDataIndex(chart, event)
            if (dataIndex === null || !boxplotData?.[dataIndex]) {
                return
            }

            const datum = boxplotData[dataIndex]
            const day = datum.day

            const actorsQuery: InsightActorsQuery = {
                kind: NodeKind.InsightActorsQuery,
                source: querySource,
                day,
                series: 0,
                includeRecordings: true,
            }

            openPersonsModal({
                title: (label: string) => (
                    <>
                        {label} on{' '}
                        <DateDisplay
                            interval={interval || 'day'}
                            resolvedDateRange={insightData?.resolved_date_range}
                            timezone={timezone}
                            weekStartDay={weekStartDay}
                            date={day}
                        />
                    </>
                ),
                query: actorsQuery,
                additionalSelect: {
                    value_at_data_point: 'event_count',
                    matched_recordings: 'matched_recordings',
                },
                orderBy: ['event_count DESC, actor_id DESC'],
            })
        },
        [showPersonsModal, querySource, boxplotData, interval, insightData, timezone, weekStartDay]
    )

    const { canvasRef } = useChart({
        getConfig: () => {
            if (!boxplotData || boxplotData.length === 0) {
                return null
            }

            return {
                type: 'boxplot' as const,
                data: {
                    labels,
                    datasets: [
                        {
                            label: 'Distribution',
                            data: chartData,
                            backgroundColor: `${seriesColor}40`,
                            borderColor: seriesColor,
                            borderWidth: 1.5,
                            medianColor: seriesColor,
                            meanBackgroundColor: `${seriesColor}80`,
                            meanBorderColor: seriesColor,
                            meanRadius: 3,
                            outlierBackgroundColor: `${seriesColor}80`,
                            outlierBorderColor: seriesColor,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 0 },
                    onClick(event: ChartEvent, _elements: unknown[], chart: Chart) {
                        handleClick(chart, event)
                    },
                    onHover(event: ChartEvent, _elements: unknown[], chart: Chart) {
                        if (event.x == null) {
                            if (activeIndexRef.current !== null) {
                                activeIndexRef.current = null
                                hideTooltip()
                            }
                            return
                        }
                        const dataIndex = getNearestDataIndex(chart, event)
                        if (dataIndex === null) {
                            if (activeIndexRef.current !== null) {
                                activeIndexRef.current = null
                                hideTooltip()
                            }
                            return
                        }
                        activeIndexRef.current = dataIndex
                        showTooltipForIndex(chart, dataIndex, event.x, event.y ?? 0)

                        chart.canvas.style.cursor = showPersonsModal ? 'pointer' : 'default'
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: { enabled: false },
                        crosshair: false as const,
                        zoom: { zoom: { drag: { enabled: false } } },
                    },
                    scales: {
                        x: {
                            ticks: {
                                color: colors.axisLabel as string,
                                font: { size: 12 },
                            },
                            grid: { display: false },
                        },
                        y: {
                            type: yAxisScaleType === 'log10' ? 'logarithmic' : 'linear',
                            ticks: {
                                color: colors.axisLabel as string,
                                font: { size: 12 },
                                callback: (value) => {
                                    return formatAggregationAxisValue(trendsFilter, value)
                                },
                            },
                            grid: {
                                color: colors.axisLine as string,
                                borderColor: colors.axisLine as string,
                            },
                        },
                    },
                },
                plugins: [],
            } as ChartConfiguration<'boxplot'>
        },
        deps: [
            chartData,
            labels,
            seriesColor,
            colors,
            showTooltipForIndex,
            hideTooltip,
            yAxisScaleType,
            handleClick,
            showPersonsModal,
            trendsFilter,
        ],
    })

    useEffect(() => {
        const canvas = canvasRef.current
        if (!canvas) {
            return
        }
        const onMouseLeave = (): void => {
            activeIndexRef.current = null
            hideTooltip()
        }
        canvas.addEventListener('mouseleave', onMouseLeave)
        return () => canvas.removeEventListener('mouseleave', onMouseLeave)
    }, [hideTooltip, canvasRef.current])

    if (!boxplotData || boxplotData.length === 0) {
        return <div className="flex items-center justify-center h-full text-muted">No data for this time range</div>
    }

    return (
        <div className="TrendsInsight w-full h-full" data-attr="box-plot-graph">
            <canvas ref={canvasRef} />
        </div>
    )
}

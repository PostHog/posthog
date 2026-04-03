import { useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import 'scenes/insights/InsightTooltip/InsightTooltip.scss'
import { Chart, ChartConfiguration, ChartEvent } from 'lib/Chart'
import { getGraphColors, getSeriesColor } from 'lib/colors'
import { DateDisplay } from 'lib/components/DateDisplay'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
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

import { BoxPlotSeriesData, boxPlotChartLogic } from './boxPlotChartLogic'

const BOX_PLOT_STATS = [
    { label: 'Max', value: (d: BoxPlotDatum) => d.max },
    { label: '75th percentile', value: (d: BoxPlotDatum) => d.p75 },
    { label: 'Median', value: (d: BoxPlotDatum) => d.median },
    { label: 'Mean', value: (d: BoxPlotDatum) => d.mean },
    { label: '25th percentile', value: (d: BoxPlotDatum) => d.p25 },
    { label: 'Min', value: (d: BoxPlotDatum) => d.min },
] as const

function seriesDataToTooltip(seriesGroups: BoxPlotSeriesData[], dataIndex: number): SeriesDatum[] {
    const result: SeriesDatum[] = []
    for (const group of seriesGroups) {
        const datum = group.rawData[dataIndex]
        if (!datum) {
            continue
        }
        const showSeriesLabel = seriesGroups.length > 1
        const color = getSeriesColor(group.seriesIndex)
        for (let statIdx = 0; statIdx < BOX_PLOT_STATS.length; statIdx++) {
            const stat = BOX_PLOT_STATS[statIdx]
            const label = showSeriesLabel ? `${group.seriesLabel} - ${stat.label}` : stat.label
            result.push({
                id: group.seriesIndex * BOX_PLOT_STATS.length + statIdx,
                dataIndex,
                datasetIndex: group.seriesIndex,
                label,
                order: group.seriesIndex * BOX_PLOT_STATS.length + statIdx,
                color,
                count: stat.value(datum),
            })
        }
    }
    return result
}

function dayForIndex(seriesGroups: BoxPlotSeriesData[], dataIndex: number): string | null {
    const datum = seriesGroups[0]?.rawData[dataIndex]
    return datum?.day ?? null
}

function hasDataAtIndex(seriesGroups: BoxPlotSeriesData[], dataIndex: number): boolean {
    return !!seriesGroups[0]?.rawData[dataIndex]
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
    const { boxplotData, seriesGroups, dateLabels, yAxisScaleType, querySource, interval, insightData, trendsFilter } =
        useValues(boxPlotChartLogic(insightProps))
    const { timezone, weekStartDay } = useValues(teamLogic)

    const colors = getGraphColors()

    const { getTooltip, hideTooltip, positionTooltip } = useInsightTooltip()
    const activeIndexRef = useRef<number | null>(null)

    const showTooltipForIndex = useCallback(
        (chart: Chart, dataIndex: number, caretX: number, caretY: number) => {
            const day = dayForIndex(seriesGroups, dataIndex)
            if (!seriesGroups.length || !day) {
                return
            }
            const [tooltipRoot, tooltipEl] = getTooltip()
            tooltipEl.classList.remove('above', 'below', 'no-transform', 'opacity-0', 'invisible')
            tooltipEl.classList.add('no-transform')
            tooltipEl.style.opacity = '1'

            const seriesData = seriesDataToTooltip(seriesGroups, dataIndex)

            tooltipRoot.render(
                <InsightTooltip
                    date={day}
                    timezone={timezone}
                    seriesData={seriesData}
                    interval={interval}
                    dateRange={insightData?.resolved_date_range}
                    hideColorCol={seriesGroups.length === 1}
                    renderSeries={(value, datum) => (
                        <div className="datum-label-column">
                            {seriesGroups.length > 1 && (
                                <SeriesLetter
                                    className="mr-2"
                                    hasBreakdown={false}
                                    seriesIndex={datum.datasetIndex}
                                    seriesColor={datum.color}
                                />
                            )}
                            {value}
                        </div>
                    )}
                    renderCount={(value: number) => formatAggregationAxisValue(trendsFilter, value)}
                    hideInspectActorsSection={!showPersonsModal}
                    groupTypeLabel="people"
                />
            )

            const bounds = chart.canvas.getBoundingClientRect()
            positionTooltip(tooltipEl, bounds, caretX, caretY)
        },
        [seriesGroups, getTooltip, positionTooltip, timezone, interval, insightData, showPersonsModal, trendsFilter]
    )

    const handleClick = useCallback(
        (chart: Chart, event: ChartEvent) => {
            if (!showPersonsModal || !querySource || event.x == null) {
                return
            }
            const dataIndex = getNearestDataIndex(chart, event)
            if (dataIndex === null || !hasDataAtIndex(seriesGroups, dataIndex)) {
                return
            }

            const day = dayForIndex(seriesGroups, dataIndex)!

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
        [showPersonsModal, querySource, seriesGroups, interval, insightData, timezone, weekStartDay]
    )

    const { canvasRef } = useChart({
        getConfig: () => {
            if (!boxplotData || boxplotData.length === 0 || seriesGroups.length === 0) {
                return null
            }

            const datasets = seriesGroups.map((group) => {
                const seriesColor = getSeriesColor(group.seriesIndex)
                return {
                    label: group.seriesLabel,
                    data: group.data,
                    backgroundColor: `${seriesColor}40`,
                    borderColor: seriesColor,
                    borderWidth: 1.5,
                    medianColor: seriesColor,
                    meanBackgroundColor: `${seriesColor}80`,
                    meanBorderColor: seriesColor,
                    meanRadius: 3,
                    outlierBackgroundColor: `${seriesColor}80`,
                    outlierBorderColor: seriesColor,
                }
            })

            return {
                type: 'boxplot' as const,
                data: {
                    labels: dateLabels,
                    datasets,
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
                        if (activeIndexRef.current !== dataIndex) {
                            activeIndexRef.current = dataIndex
                            const tickX = chart.scales.x?.getPixelForTick(dataIndex) ?? event.x
                            showTooltipForIndex(chart, dataIndex, tickX, 0)
                        }

                        chart.canvas.style.cursor = showPersonsModal ? 'pointer' : 'default'
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: { enabled: false },
                        crosshair: {
                            snap: { enabled: true },
                            sync: { enabled: false },
                            zoom: { enabled: false },
                            line: {
                                color: colors.crosshair ?? undefined,
                                width: 1,
                            },
                        },
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
            boxplotData,
            seriesGroups,
            dateLabels,
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
        <div className="w-full grow relative overflow-hidden" data-attr="box-plot-graph">
            <canvas ref={canvasRef} />
        </div>
    )
}

import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { BoxPlot } from '@posthog/quill-charts'
import type { BoxPlotClickData, BoxPlotConfig, BoxPlotSeries, BoxPlotTooltipContext } from '@posthog/quill-charts'

import 'scenes/insights/InsightTooltip/InsightTooltip.scss'
import { buildTheme } from 'lib/charts/utils/theme'
import { getSeriesColor } from 'lib/colors'
import { DateDisplay } from 'lib/components/DateDisplay'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
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

export function BoxPlotChart({ showPersonsModal = true }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { boxplotData, seriesGroups, dateLabels, yAxisScaleType, querySource, interval, insightData, trendsFilter } =
        useValues(boxPlotChartLogic(insightProps))
    const { timezone, weekStartDay } = useValues(teamLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const quillTooltipEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_INSIGHTS_TOOLTIPS]

    // isDarkModeOn invalidates the memo so buildTheme() re-reads CSS vars on dark-mode toggle.
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])

    const series = useMemo<BoxPlotSeries[]>(
        () =>
            seriesGroups.map((group) => ({
                key: String(group.seriesIndex),
                label: group.seriesLabel,
                // Explicit color keeps boxes in sync with BoxPlotLegend / BoxPlotResultsTable.
                color: getSeriesColor(group.seriesIndex),
                // Feed whisker bounds as min/max — quill draws whiskers at min/max, so this
                // preserves the exclude-outliers (±1.5·IQR) behaviour computed in the logic.
                data: group.rawData.map((raw, i) => ({
                    min: group.data[i].whiskerMin,
                    p25: raw.p25,
                    median: raw.median,
                    mean: raw.mean,
                    p75: raw.p75,
                    max: group.data[i].whiskerMax,
                    day: raw.day,
                })),
            })),
        [seriesGroups]
    )

    const formatValue = useCallback((value: number) => formatAggregationAxisValue(trendsFilter, value), [trendsFilter])

    const config = useMemo<BoxPlotConfig>(
        () => ({
            yScaleType: yAxisScaleType === 'log10' ? 'log' : 'linear',
            yTickFormatter: formatValue,
            showGrid: true,
            tooltip: quillTooltipEnabled ? { pinnable: true, placement: 'cursor' } : undefined,
        }),
        [yAxisScaleType, formatValue, quillTooltipEnabled]
    )

    const renderTooltip = useCallback(
        (ctx: BoxPlotTooltipContext): JSX.Element | null => {
            const dataIndex = ctx.dataIndex
            const day = seriesGroups[0]?.rawData[dataIndex]?.day
            if (!seriesGroups.length || !day) {
                return null
            }
            return (
                <InsightTooltip
                    date={day}
                    timezone={timezone}
                    seriesData={seriesDataToTooltip(seriesGroups, dataIndex)}
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
                    renderCount={(value: number) => formatValue(value)}
                    hideInspectActorsSection={!showPersonsModal}
                    groupTypeLabel="people"
                />
            )
        },
        [seriesGroups, timezone, interval, insightData, showPersonsModal, formatValue]
    )

    const handleBoxClick = useCallback(
        (data: BoxPlotClickData): void => {
            if (!showPersonsModal || !querySource) {
                return
            }
            const day = seriesGroups[0]?.rawData[data.dataIndex]?.day
            if (!day) {
                return
            }

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

    if (!boxplotData || boxplotData.length === 0) {
        return <div className="flex items-center justify-center h-full text-muted">No data for this time range</div>
    }

    return (
        <div className="w-full grow relative overflow-hidden flex flex-col">
            <BoxPlot
                series={series}
                labels={dateLabels}
                theme={theme}
                config={config}
                tooltip={quillTooltipEnabled ? undefined : renderTooltip}
                onBoxClick={handleBoxClick}
                dataAttr="box-plot-graph"
            />
        </div>
    )
}

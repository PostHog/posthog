import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { createXAxisTickCallback } from 'lib/charts/utils/dates'
import { buildTheme } from 'lib/charts/utils/theme'
import { DEFAULT_Y_AXIS_ID, LineChart } from 'lib/hog-charts'
import type { LineChartConfig, PointClickData, Series } from 'lib/hog-charts'
import type { TooltipContext } from 'lib/hog-charts/core/types'
import { ReferenceLines } from 'lib/hog-charts/overlays/ReferenceLine'
import { ValueLabels } from 'lib/hog-charts/overlays/ValueLabels'
import { ciRanges, movingAverage, trendLine } from 'lib/statistics'
import { hexToRGBA } from 'lib/utils'
import { formatPercentStackAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { groupsModel } from '~/models/groupsModel'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType } from '~/types'

import { InsightEmptyState } from '../../insights/EmptyStates'
import { openPersonsModal } from '../persons-modal/PersonsModal'
import { trendsDataLogic } from '../trendsDataLogic'
import type { IndexedTrendResult } from '../types'
import { goalLinesToReferenceLines } from './goalLinesAdapter'
import { handleTrendsLineChartClick } from './handleTrendsLineChartClick'
import type { TrendsSeriesMeta } from './trendsSeriesMeta'
import { TrendsTooltip } from './TrendsTooltip'

interface TrendsLineChartD3Props {
    context?: QueryContext<InsightVizNode>
}

export function TrendsLineChartD3({ context }: TrendsLineChartD3Props): JSX.Element | null {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])
    const { insightProps } = useValues(insightLogic)

    const {
        indexedResults,
        display,
        interval,
        showPercentStackView,
        supportsPercentStackView,
        yAxisScaleType,
        showMultipleYAxes,
        goalLines,
        getTrendsColor,
        getTrendsHidden,
        currentPeriodResult,
        breakdownFilter,
        insightData,
        trendsFilter,
        formula,
        isStickiness,
        labelGroupType,
        hasPersonsModal,
        querySource,
        incompletenessOffsetFromEnd,
        showMovingAverage,
        movingAverageIntervals,
        showTrendLines,
        showValuesOnSeries,
        showConfidenceIntervals,
        confidenceLevel,
    } = useValues(trendsDataLogic(insightProps))
    const { timezone, weekStartDay, baseCurrency } = useValues(teamLogic)
    const { aggregationLabel } = useValues(groupsModel)

    const isPercentStackView = !!showPercentStackView && !!supportsPercentStackView
    const resolvedGroupTypeLabel =
        context?.groupTypeLabel ??
        (labelGroupType === 'people'
            ? 'people'
            : labelGroupType === 'none'
              ? ''
              : aggregationLabel(labelGroupType).plural)

    const labels = currentPeriodResult?.labels ?? []

    const hasData =
        indexedResults &&
        indexedResults[0]?.data &&
        indexedResults.filter((result: IndexedTrendResult) => result.count !== 0).length > 0

    // Dash the in-progress tail (mirrors LineGraph.tsx). Stickiness indices aren't dates.
    const isInProgress = !isStickiness && incompletenessOffsetFromEnd < 0

    const hogSeries: Series<TrendsSeriesMeta>[] = useMemo(
        () =>
            (indexedResults ?? []).flatMap((r: IndexedTrendResult, index: number) => {
                const isActiveSeries = !r.compare || r.compare_label !== 'previous'
                const dashedFromIndex =
                    isInProgress && isActiveSeries ? r.data.length + incompletenessOffsetFromEnd : undefined
                const yAxisId = showMultipleYAxes && index > 0 ? `y${index}` : DEFAULT_Y_AXIS_ID
                const meta: TrendsSeriesMeta = {
                    action: r.action,
                    breakdown_value: r.breakdown_value,
                    compare_label: r.compare_label,
                    days: r.days,
                    order: r.action?.order ?? r.id,
                    filter: r.filter,
                }
                const baseColor = getTrendsColor(r)
                const displayColor = r.compare_label === 'previous' ? hexToRGBA(baseColor, 0.5) : baseColor
                const hidden = getTrendsHidden(r)
                const mainSeries: Series<TrendsSeriesMeta> = {
                    key: `${r.id}`,
                    label: r.label ?? '',
                    data: r.data,
                    color: displayColor,
                    fillArea: display === ChartDisplayType.ActionsAreaGraph,
                    dashedFromIndex,
                    hidden,
                    yAxisId,
                    meta,
                }
                const series: Series<TrendsSeriesMeta>[] = [mainSeries]

                if (showConfidenceIntervals) {
                    const [lower, upper] = ciRanges(r.data, confidenceLevel / 100)
                    series.push({
                        key: `${r.id}__ci`,
                        label: `${r.label ?? ''} (CI)`,
                        data: upper,
                        fillBetweenData: lower,
                        color: displayColor,
                        fillArea: true,
                        fillOpacity: 0.2,
                        pointRadius: 0,
                        hidden: hidden,
                        hideFromTooltip: true,
                        hideValueLabels: true,
                        yAxisId,
                        meta,
                    })
                }

                if (showMovingAverage && r.data.length >= movingAverageIntervals) {
                    const maData = movingAverage(r.data, movingAverageIntervals)
                    series.push({
                        key: `${r.id}-ma`,
                        label: `${r.label ?? ''} (Moving avg)`,
                        data: maData,
                        color: displayColor,
                        fillArea: false,
                        dashPattern: [10, 3],
                        pointRadius: 0,
                        hideFromTooltip: true,
                        excludeFromStack: true,
                        yAxisId,
                        meta,
                    })

                    if (showTrendLines && !hidden) {
                        series.push({
                            key: `${r.id}-ma__trendline`,
                            label: `${r.label ?? ''} (Moving avg)`,
                            data: trendLine(maData),
                            color: hexToRGBA(baseColor, 0.5),
                            yAxisId,
                            dashPattern: [1, 3],
                            pointRadius: 0,
                            hideFromTooltip: true,
                            excludeFromStack: true,
                            hideValueLabels: true,
                        })
                    }
                }

                // Fit excludes the in-progress tail (dashedFromIndex..end) so the flat
                // partial bucket doesn't drag the slope down. Dimmed so the dashed
                // overlay reads as subordinate to the series line — at full intensity
                // the two colors visually compete, especially on a dark background.
                if (showTrendLines && !hidden) {
                    series.push({
                        key: `${r.id}__trendline`,
                        label: r.label ?? '',
                        data: trendLine(r.data, dashedFromIndex),
                        color: hexToRGBA(baseColor, 0.5),
                        yAxisId,
                        dashPattern: [1, 3],
                        pointRadius: 0,
                        hideFromTooltip: true,
                        excludeFromStack: true,
                        hideValueLabels: true,
                    })
                }

                return series
            }),
        [
            indexedResults,
            display,
            getTrendsColor,
            getTrendsHidden,
            isInProgress,
            incompletenessOffsetFromEnd,
            showMultipleYAxes,
            showMovingAverage,
            movingAverageIntervals,
            showTrendLines,
            showConfidenceIntervals,
            confidenceLevel,
        ]
    )

    const chartConfig: LineChartConfig = useMemo(() => {
        const xTickFormatter = createXAxisTickCallback({
            interval: interval ?? 'day',
            allDays: currentPeriodResult?.days ?? [],
            timezone,
        })
        return {
            showGrid: true,
            showCrosshair: true,
            pinnableTooltip: true,
            yScaleType: yAxisScaleType === 'log10' ? 'log' : 'linear',
            percentStackView: isPercentStackView,
            xTickFormatter,
        }
    }, [interval, currentPeriodResult?.days, timezone, yAxisScaleType, isPercentStackView])

    const referenceLines = useMemo(() => goalLinesToReferenceLines(goalLines, hogSeries), [goalLines, hogSeries])

    const valueLabelFormatter = useCallback(
        (value: number) => formatPercentStackAxisValue(trendsFilter, value, isPercentStackView, baseCurrency),
        [trendsFilter, isPercentStackView, baseCurrency]
    )

    const canHandleClick = !!context?.onDataPointClick || !!hasPersonsModal

    const clickDeps = useMemo(
        () => ({
            context,
            hasPersonsModal: !!hasPersonsModal,
            interval,
            timezone,
            weekStartDay,
            resolvedDateRange: insightData?.resolved_date_range ?? null,
            querySource,
            indexedResults: indexedResults ?? [],
            openPersonsModal,
        }),
        [
            context,
            hasPersonsModal,
            interval,
            timezone,
            weekStartDay,
            insightData?.resolved_date_range,
            querySource,
            indexedResults,
            openPersonsModal,
        ]
    )

    const onPointClick = useCallback(
        (clickData: PointClickData) => {
            handleTrendsLineChartClick(clickData.series.key, clickData.dataIndex, clickDeps)
        },
        [clickDeps]
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => {
            const onRowClick = canHandleClick
                ? (datum: SeriesDatum) => {
                      const seriesKey = ctx.seriesData[datum.datasetIndex].series.key
                      handleTrendsLineChartClick(seriesKey, datum.dataIndex, clickDeps)
                  }
                : undefined
            return (
                <TrendsTooltip
                    context={ctx}
                    timezone={timezone}
                    interval={interval ?? undefined}
                    breakdownFilter={breakdownFilter ?? undefined}
                    dateRange={insightData?.resolved_date_range ?? undefined}
                    trendsFilter={trendsFilter}
                    formula={formula}
                    showPercentView={isStickiness}
                    isPercentStackView={isPercentStackView}
                    baseCurrency={baseCurrency}
                    groupTypeLabel={resolvedGroupTypeLabel}
                    formatCompareLabel={context?.formatCompareLabel}
                    onRowClick={onRowClick}
                />
            )
        },
        [
            timezone,
            interval,
            breakdownFilter,
            insightData?.resolved_date_range,
            trendsFilter,
            formula,
            isStickiness,
            isPercentStackView,
            baseCurrency,
            resolvedGroupTypeLabel,
            context?.formatCompareLabel,
            canHandleClick,
            clickDeps,
        ]
    )

    if (!hasData) {
        return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
    }

    return (
        <LineChart
            series={hogSeries}
            labels={labels}
            config={chartConfig}
            theme={theme}
            tooltip={renderTooltip}
            onPointClick={canHandleClick ? onPointClick : undefined}
            className="LineGraph"
        >
            <ReferenceLines lines={referenceLines} />
            {showValuesOnSeries && <ValueLabels valueFormatter={valueLabelFormatter} />}
        </LineChart>
    )
}

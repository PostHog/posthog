import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { createXAxisTickCallback } from 'lib/charts/utils/dates'
import { buildTheme } from 'lib/charts/utils/theme'
import { DEFAULT_Y_AXIS_ID, LineChart, ReferenceLines, ValueLabels } from 'lib/hog-charts'
import type { LineChartConfig, PointClickData, Series, TooltipContext } from 'lib/hog-charts'
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
import { AnnotationsLayer } from './AnnotationsLayer'
import { goalLinesToReferenceLines } from './goalLinesAdapter'
import { handleTrendsLineChartClick } from './handleTrendsLineChartClick'
import { TrendsAlertOverlays } from './TrendsAlertOverlays'
import { buildTrendsYTickFormatter } from './trendsAxisFormat'
import type { TrendsSeriesMeta } from './trendsSeriesMeta'
import { TrendsTooltip } from './TrendsTooltip'

interface TrendsLineChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
}

export function TrendsLineChart({ context, inSharedMode = false }: TrendsLineChartProps): JSX.Element | null {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])
    const { insightProps, insight } = useValues(insightLogic)

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
                const excluded = getTrendsHidden(r)
                const mainSeries: Series<TrendsSeriesMeta> = {
                    key: `${r.id}`,
                    label: r.label ?? '',
                    data: r.data,
                    color: displayColor,
                    yAxisId,
                    meta,
                    fill: display === ChartDisplayType.ActionsAreaGraph ? {} : undefined,
                    stroke: dashedFromIndex !== undefined ? { partial: { fromIndex: dashedFromIndex } } : undefined,
                    visibility: excluded ? { excluded: true } : undefined,
                }
                const series: Series<TrendsSeriesMeta>[] = [mainSeries]

                if (showConfidenceIntervals) {
                    const [lower, upper] = ciRanges(r.data, confidenceLevel / 100)
                    series.push({
                        key: `${r.id}__ci`,
                        label: `${r.label ?? ''} (CI)`,
                        data: upper,
                        color: displayColor,
                        yAxisId,
                        meta,
                        fill: { opacity: 0.2, lowerData: lower },
                        visibility: { excluded, fromTooltip: true, fromValueLabels: true },
                    })
                }

                if (showMovingAverage && r.data.length >= movingAverageIntervals) {
                    const maData = movingAverage(r.data, movingAverageIntervals)
                    series.push({
                        key: `${r.id}-ma`,
                        label: `${r.label ?? ''} (Moving avg)`,
                        data: maData,
                        color: displayColor,
                        yAxisId,
                        meta,
                        stroke: { pattern: [10, 3] },
                        visibility: { fromTooltip: true, fromStack: true },
                    })

                    if (showTrendLines && !excluded) {
                        series.push({
                            key: `${r.id}-ma__trendline`,
                            label: `${r.label ?? ''} (Moving avg)`,
                            data: trendLine(maData),
                            color: hexToRGBA(baseColor, 0.5),
                            yAxisId,
                            stroke: { pattern: [1, 3] },
                            visibility: { fromTooltip: true, fromValueLabels: true, fromStack: true },
                        })
                    }
                }

                // Fit excludes the in-progress tail (dashedFromIndex..end) so the flat
                // partial bucket doesn't drag the slope down. Dimmed so the dashed
                // overlay reads as subordinate to the series line — at full intensity
                // the two colors visually compete, especially on a dark background.
                if (showTrendLines && !excluded) {
                    series.push({
                        key: `${r.id}__trendline`,
                        label: r.label ?? '',
                        data: trendLine(r.data, dashedFromIndex),
                        color: hexToRGBA(baseColor, 0.5),
                        yAxisId,
                        stroke: { pattern: [1, 3] },
                        visibility: { fromTooltip: true, fromValueLabels: true, fromStack: true },
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

    const xTickFormatter = useMemo(
        () =>
            createXAxisTickCallback({
                interval: interval ?? 'day',
                allDays: currentPeriodResult?.days ?? [],
                timezone,
            }),
        [interval, currentPeriodResult?.days, timezone]
    )

    const yTickFormatter = useMemo(
        () => buildTrendsYTickFormatter(trendsFilter, isPercentStackView, baseCurrency),
        [trendsFilter, isPercentStackView, baseCurrency]
    )

    const chartConfig: LineChartConfig = useMemo(
        () => ({
            showGrid: true,
            showCrosshair: true,
            tooltip: { pinnable: true, placement: 'top' },
            yScaleType: yAxisScaleType === 'log10' ? 'log' : 'linear',
            percentStackView: isPercentStackView,
            xTickFormatter,
            yTickFormatter,
        }),
        [yAxisScaleType, isPercentStackView, xTickFormatter, yTickFormatter]
    )

    const referenceLines = useMemo(() => goalLinesToReferenceLines(goalLines, hogSeries), [goalLines, hogSeries])

    const getYAxisId = useCallback(
        (r: IndexedTrendResult) => {
            const idx = (indexedResults ?? []).indexOf(r)
            return showMultipleYAxes && idx > 0 ? `y${idx}` : DEFAULT_Y_AXIS_ID
        },
        [indexedResults, showMultipleYAxes]
    )

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

    const showAnnotations = !inSharedMode
    const annotationsDates = currentPeriodResult?.days ?? []

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
            {insight.id ? (
                <TrendsAlertOverlays
                    insightId={insight.id}
                    insightProps={insightProps}
                    indexedResults={indexedResults}
                    getColor={getTrendsColor}
                    getYAxisId={getYAxisId}
                    isHidden={getTrendsHidden}
                />
            ) : null}
            {showValuesOnSeries && <ValueLabels valueFormatter={valueLabelFormatter} />}
            {showAnnotations && (
                <AnnotationsLayer
                    insightNumericId={insight.id || 'new'}
                    dates={annotationsDates}
                    xTickFormatter={xTickFormatter}
                />
            )}
        </LineChart>
    )
}

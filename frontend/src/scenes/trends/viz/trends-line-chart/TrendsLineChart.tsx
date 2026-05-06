import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { DEFAULT_Y_AXIS_ID, TimeSeriesLineChart } from 'lib/hog-charts'
import type { PointClickData, Series, TimeSeriesLineChartConfig, TooltipConfig, TooltipContext } from 'lib/hog-charts'
import { formatPercentStackAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { groupsModel } from '~/models/groupsModel'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { InsightEmptyState } from '../../../insights/EmptyStates'
import { openPersonsModal } from '../../persons-modal/PersonsModal'
import { trendsDataLogic } from '../../trendsDataLogic'
import type { IndexedTrendResult } from '../../types'
import { handleTrendsChartClick } from '../handleTrendsChartClick'
import { AnnotationsLayer } from './AnnotationsLayer'
import { schemaGoalLinesToConfigs } from './goalLinesAdapter'
import { TrendsAlertOverlays } from './TrendsAlertOverlays'
import { buildTrendsYAxisConfig } from './trendsAxisFormat'
import { buildDerivedConfigs, buildTrendsSeries } from './trendsChartTransforms'
import type { TrendsSeriesMeta } from './trendsSeriesMeta'
import { TrendsTooltip } from './TrendsTooltip'

interface TrendsLineChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
}

const TOOLTIP_CONFIG: TooltipConfig = { pinnable: true, placement: 'top' }

const handleChartError = (error: Error, info: ErrorInfo): void => {
    posthog.captureException(error, {
        feature: 'trends-line-chart',
        componentStack: info.componentStack ?? undefined,
    })
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

    const series: Series<TrendsSeriesMeta>[] = useMemo(
        () =>
            buildTrendsSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
                display: display ?? undefined,
                showMultipleYAxes: showMultipleYAxes ?? undefined,
                incompletenessOffsetFromEnd,
                isStickiness,
                getColor: getTrendsColor,
                getHidden: getTrendsHidden,
                buildMeta: (rr) => ({
                    action: rr.action,
                    breakdown_value: rr.breakdown_value,
                    compare_label: rr.compare_label,
                    days: rr.days,
                    order: rr.action?.order ?? rr.id,
                    filter: rr.filter,
                }),
            }),
        [
            indexedResults,
            display,
            getTrendsColor,
            getTrendsHidden,
            isStickiness,
            incompletenessOffsetFromEnd,
            showMultipleYAxes,
        ]
    )

    const yAxisConfig = useMemo(
        () =>
            buildTrendsYAxisConfig(trendsFilter, isPercentStackView, baseCurrency, {
                yAxisScaleType,
                showGrid: true,
            }),
        [trendsFilter, isPercentStackView, baseCurrency, yAxisScaleType]
    )

    const goalLineConfigs = useMemo(() => schemaGoalLinesToConfigs(goalLines), [goalLines])

    const valueLabelFormatter = useCallback(
        (value: number) => formatPercentStackAxisValue(trendsFilter, value, isPercentStackView, baseCurrency),
        [trendsFilter, isPercentStackView, baseCurrency]
    )

    const derivedConfigs = useMemo(
        () =>
            buildDerivedConfigs(indexedResults ?? [], {
                showConfidenceIntervals,
                confidenceLevel,
                showMovingAverage,
                movingAverageIntervals,
                showTrendLines,
                isStickiness,
                incompletenessOffsetFromEnd,
                getHidden: getTrendsHidden,
            }),
        [
            indexedResults,
            showConfidenceIntervals,
            confidenceLevel,
            showMovingAverage,
            movingAverageIntervals,
            showTrendLines,
            isStickiness,
            incompletenessOffsetFromEnd,
            getTrendsHidden,
        ]
    )

    const chartConfig: TimeSeriesLineChartConfig = useMemo(
        () => ({
            xAxis: {
                timezone,
                interval: interval ?? 'day',
                allDays: currentPeriodResult?.days ?? [],
            },
            yAxis: yAxisConfig,
            valueLabels: showValuesOnSeries ? { formatter: valueLabelFormatter } : false,
            goalLines: goalLineConfigs,
            ...derivedConfigs,
            percentStackView: isPercentStackView,
            showCrosshair: true,
            tooltip: TOOLTIP_CONFIG,
        }),
        [
            timezone,
            interval,
            currentPeriodResult?.days,
            yAxisConfig,
            showValuesOnSeries,
            valueLabelFormatter,
            goalLineConfigs,
            derivedConfigs,
            isPercentStackView,
        ]
    )

    const indexByResult = useMemo(() => {
        const m = new Map<IndexedTrendResult, number>()
        ;(indexedResults ?? []).forEach((r, i) => m.set(r, i))
        return m
    }, [indexedResults])

    const getYAxisId = useCallback(
        (r: IndexedTrendResult) => {
            const idx = indexByResult.get(r) ?? 0
            return showMultipleYAxes && idx > 0 ? `y${idx}` : DEFAULT_Y_AXIS_ID
        },
        [indexByResult, showMultipleYAxes]
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
            handleTrendsChartClick(clickData.series.key, clickData.dataIndex, clickDeps)
        },
        [clickDeps]
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => {
            const onRowClick = canHandleClick
                ? (datum: SeriesDatum) => {
                      const seriesKey = ctx.seriesData[datum.datasetIndex].series.key
                      handleTrendsChartClick(seriesKey, datum.dataIndex, clickDeps)
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
        <TimeSeriesLineChart<TrendsSeriesMeta>
            series={series}
            labels={labels}
            theme={theme}
            config={chartConfig}
            tooltip={renderTooltip}
            onPointClick={canHandleClick ? onPointClick : undefined}
            className="LineGraph"
            dataAttr="trend-line-graph"
            onError={handleChartError}
        >
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
            {showAnnotations && <AnnotationsLayer insightNumericId={insight.id || 'new'} dates={annotationsDates} />}
        </TimeSeriesLineChart>
    )
}

import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import { createXAxisTickCallback } from 'lib/charts/utils/dates'
import { buildTheme } from 'lib/charts/utils/theme'
import { DEFAULT_Y_AXIS_ID, LineChart, ReferenceLines, ValueLabels } from 'lib/hog-charts'
import type { LineChartConfig, PointClickData, Series, TooltipContext } from 'lib/hog-charts'
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
import { AnnotationsLayer } from './AnnotationsLayer'
import { goalLinesToReferenceLines } from './goalLinesAdapter'
import { handleTrendsLineChartClick } from './handleTrendsLineChartClick'
import { TrendsAlertOverlays } from './TrendsAlertOverlays'
import { buildTrendsYTickFormatter } from './trendsAxisFormat'
import { buildTrendsChartConfig, buildTrendsSeries } from './trendsChartTransforms'
import type { TrendsSeriesMeta } from './trendsSeriesMeta'
import { TrendsTooltip } from './TrendsTooltip'

interface TrendsLineChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
}

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
                showConfidenceIntervals,
                confidenceLevel,
                showMovingAverage,
                movingAverageIntervals,
                showTrendLines,
            }),
        [
            indexedResults,
            display,
            getTrendsColor,
            getTrendsHidden,
            isStickiness,
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
        () =>
            buildTrendsChartConfig({
                yAxisScaleType,
                isPercentStackView,
                showGrid: true,
                showCrosshair: true,
                pinnableTooltip: true,
                tooltipPlacement: 'top',
                xTickFormatter,
                yTickFormatter,
            }),
        [yAxisScaleType, isPercentStackView, xTickFormatter, yTickFormatter]
    )

    const referenceLines = useMemo(() => goalLinesToReferenceLines(goalLines, series), [goalLines, series])

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
            series={series}
            labels={labels}
            config={chartConfig}
            theme={theme}
            tooltip={renderTooltip}
            onPointClick={canHandleClick ? onPointClick : undefined}
            className="LineGraph"
            onError={handleChartError}
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

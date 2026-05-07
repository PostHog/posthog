import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import {
    BarChart,
    buildYTickFormatter,
    createXAxisTickCallback,
    DEFAULT_Y_AXIS_ID,
    ReferenceLines,
    ValueLabels,
} from 'lib/hog-charts'
import type { BarChartConfig, PointClickData, TooltipContext } from 'lib/hog-charts'
import { formatPercentStackAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType } from '~/types'

import { openPersonsModal } from '../../persons-modal/PersonsModal'
import { trendsDataLogic } from '../../trendsDataLogic'
import type { IndexedTrendResult } from '../../types'
import { handleTrendsChartClick, type TrendsChartClickDeps } from '../handleTrendsChartClick'
import { AnnotationsLayer } from '../trends-line-chart/AnnotationsLayer'
import { goalLinesToReferenceLines } from '../trends-line-chart/goalLinesAdapter'
import { TrendsAlertOverlays } from '../trends-line-chart/TrendsAlertOverlays'
import { trendsFilterToYFormatterConfig } from '../trends-line-chart/trendsAxisFormat'
import type { TrendsSeriesMeta } from '../trends-line-chart/trendsSeriesMeta'
import { TrendsTooltip } from '../trends-line-chart/TrendsTooltip'
import { handleTrendsBarAggregatedChartClick } from './handleTrendsBarAggregatedChartClick'
import { buildTrendsBarAggregatedSeries, buildTrendsBarTimeSeries } from './trendsBarChartTransforms'

interface TrendsBarChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
}

const EMPTY_LABELS: string[] = []

const buildBarMeta = (r: IndexedTrendResult): TrendsSeriesMeta => ({
    action: r.action,
    breakdown_value: r.breakdown_value,
    compare_label: r.compare_label,
    days: r.days,
    order: r.action?.order ?? r.id,
    filter: r.filter,
})

type AggregationLabelFn = (groupTypeIndex: number | null | undefined) => { plural: string }

const resolveGroupTypeLabel = (
    labelGroupType: 'people' | 'none' | number,
    aggregationLabel: AggregationLabelFn,
    contextOverride: string | undefined
): string => {
    if (contextOverride != null) {
        return contextOverride
    }
    if (labelGroupType === 'people') {
        return 'people'
    }
    if (labelGroupType === 'none') {
        return ''
    }
    return aggregationLabel(labelGroupType).plural
}

const handleChartError = (error: Error, info: ErrorInfo): void => {
    posthog.captureException(error, {
        feature: 'trends-bar-chart',
        componentStack: info.componentStack ?? undefined,
    })
}

export function TrendsBarChart({ context, inSharedMode = false }: TrendsBarChartProps): JSX.Element | null {
    const theme = useMemo(() => buildTheme(), [])
    const { insightProps, insight } = useValues(insightLogic)

    const {
        indexedResults,
        display,
        interval,
        showPercentStackView,
        supportsPercentStackView,
        yAxisScaleType,
        currentPeriodResult,
        breakdownFilter,
        insightData,
        trendsFilter,
        formula,
        isStickiness,
        labelGroupType,
        hasPersonsModal,
        querySource,
        getTrendsColor,
        getTrendsHidden,
        goalLines,
        showValuesOnSeries,
    } = useValues(trendsDataLogic(insightProps))
    const { timezone, weekStartDay, baseCurrency } = useValues(teamLogic)
    const { aggregationLabel } = useValues(groupsModel)

    const isAggregated = display === ChartDisplayType.ActionsBarValue
    const isGrouped = display === ChartDisplayType.ActionsUnstackedBar
    const isPercentStackView = !isAggregated && !!showPercentStackView && !!supportsPercentStackView

    const resolvedGroupTypeLabel = resolveGroupTypeLabel(labelGroupType, aggregationLabel, context?.groupTypeLabel)

    const hasData =
        !!indexedResults?.[0] &&
        (isAggregated
            ? indexedResults.some(
                  (r: IndexedTrendResult) => Number.isFinite(r.aggregated_value) && r.aggregated_value !== 0
              )
            : !!indexedResults[0].data && indexedResults.some((r: IndexedTrendResult) => r.count !== 0))

    const { series, labels } = useMemo(() => {
        if (isAggregated) {
            return buildTrendsBarAggregatedSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
                getColor: getTrendsColor,
                getHidden: getTrendsHidden,
                buildMeta: buildBarMeta,
            })
        }
        const timeSeries = buildTrendsBarTimeSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
            getColor: getTrendsColor,
            getHidden: getTrendsHidden,
            buildMeta: buildBarMeta,
        })
        return { series: timeSeries, labels: currentPeriodResult?.labels ?? EMPTY_LABELS }
    }, [isAggregated, indexedResults, getTrendsColor, getTrendsHidden, currentPeriodResult?.labels])

    const xTickFormatter = useMemo(() => {
        if (isAggregated) {
            return undefined
        }
        return createXAxisTickCallback({
            interval: interval ?? 'day',
            allDays: currentPeriodResult?.days ?? [],
            timezone,
        })
    }, [isAggregated, interval, currentPeriodResult?.days, timezone])

    const yTickFormatter = useMemo(
        () => buildYTickFormatter(trendsFilterToYFormatterConfig(trendsFilter, isPercentStackView, baseCurrency)),
        [trendsFilter, isPercentStackView, baseCurrency]
    )

    const chartConfig: BarChartConfig = useMemo(
        () => ({
            showGrid: true,
            tooltip: { pinnable: true, placement: 'top' },
            yScaleType: yAxisScaleType === 'log10' ? 'log' : 'linear',
            axisOrientation: isAggregated ? 'horizontal' : 'vertical',
            barLayout: isPercentStackView ? 'percent' : isGrouped ? 'grouped' : 'stacked',
            xTickFormatter,
            yTickFormatter,
        }),
        [yAxisScaleType, isAggregated, isGrouped, isPercentStackView, xTickFormatter, yTickFormatter]
    )

    const canHandleClick = !!context?.onDataPointClick || !!hasPersonsModal

    const clickDeps = useMemo<TrendsChartClickDeps>(
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
        ]
    )

    const valueLabelFormatter = useCallback(
        (value: number) => formatPercentStackAxisValue(trendsFilter, value, isPercentStackView, baseCurrency),
        [trendsFilter, isPercentStackView, baseCurrency]
    )

    const overlayAxisOrientation: 'vertical' | 'horizontal' = isAggregated ? 'horizontal' : 'vertical'

    const referenceLines = useMemo(
        () => goalLinesToReferenceLines(goalLines, series, overlayAxisOrientation),
        [goalLines, series, overlayAxisOrientation]
    )

    // Bar charts don't yet expose multi-axis configuration, so all series live on the
    // primary axis — alert anomaly markers always read the default scale.
    const getYAxisId = useCallback(() => DEFAULT_Y_AXIS_ID, [])

    const onPointClick = useCallback(
        (clickData: PointClickData) => {
            if (isAggregated) {
                handleTrendsBarAggregatedChartClick(clickData.dataIndex, clickDeps)
            } else {
                handleTrendsChartClick(clickData.series.key, clickData.dataIndex, clickDeps)
            }
        },
        [isAggregated, clickDeps]
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => {
            // Sparse-stacked: drop sibling series with data=0 at this band so the tooltip shows one row.
            const tooltipCtx: TooltipContext<TrendsSeriesMeta> = isAggregated
                ? {
                      ...ctx,
                      seriesData: ctx.seriesData.filter((entry) => {
                          const raw = entry.series.data[ctx.dataIndex]
                          return typeof raw === 'number' && raw !== 0
                      }),
                  }
                : ctx
            const onRowClick = canHandleClick
                ? (datum: SeriesDatum) => {
                      if (isAggregated) {
                          handleTrendsBarAggregatedChartClick(datum.dataIndex, clickDeps)
                      } else {
                          const seriesKey = tooltipCtx.seriesData[datum.datasetIndex].series.key
                          handleTrendsChartClick(seriesKey, datum.dataIndex, clickDeps)
                      }
                  }
                : undefined
            return (
                <TrendsTooltip
                    context={tooltipCtx}
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
            isAggregated,
        ]
    )

    if (!hasData) {
        return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
    }

    // Annotations are date-anchored, so they only make sense for the time-series bar
    // layouts (vertical bars). The horizontal aggregated layout has categorical labels.
    const showAnnotations = !inSharedMode && !isAggregated
    const annotationsDates = currentPeriodResult?.days ?? []

    return (
        <BarChart<TrendsSeriesMeta>
            series={series}
            labels={labels}
            config={chartConfig}
            theme={theme}
            tooltip={renderTooltip}
            onPointClick={canHandleClick ? onPointClick : undefined}
            className="BarGraph"
            dataAttr={isAggregated ? 'trend-bar-value-graph' : 'trend-bar-graph'}
            onError={handleChartError}
        >
            <ReferenceLines lines={referenceLines} />
            {insight.id && (
                <TrendsAlertOverlays
                    insightId={insight.id}
                    insightProps={insightProps}
                    indexedResults={indexedResults}
                    getColor={getTrendsColor}
                    getYAxisId={getYAxisId}
                    isHidden={getTrendsHidden}
                    axisOrientation={overlayAxisOrientation}
                />
            )}
            {showValuesOnSeries && <ValueLabels valueFormatter={valueLabelFormatter} />}
            {showAnnotations && <AnnotationsLayer insightNumericId={insight.id || 'new'} dates={annotationsDates} />}
        </BarChart>
    )
}

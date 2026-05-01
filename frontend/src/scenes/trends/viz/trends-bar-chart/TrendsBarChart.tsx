import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import { createXAxisTickCallback } from 'lib/charts/utils/dates'
import { buildTheme } from 'lib/charts/utils/theme'
import { BarChart } from 'lib/hog-charts'
import type { BarChartConfig, PointClickData, TooltipContext } from 'lib/hog-charts'
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
import { buildTrendsYTickFormatter } from '../trends-line-chart/trendsAxisFormat'
import type { TrendsSeriesMeta } from '../trends-line-chart/trendsSeriesMeta'
import { TrendsTooltip } from '../trends-line-chart/TrendsTooltip'
import { handleTrendsBarChartClick, type TrendsBarChartClickDeps } from './handleTrendsBarChartClick'
import { buildTrendsBarTimeSeries } from './trendsBarChartTransforms'

interface TrendsBarChartProps {
    context?: QueryContext<InsightVizNode>
    inSharedMode?: boolean
}

const handleChartError = (error: Error, info: ErrorInfo): void => {
    posthog.captureException(error, {
        feature: 'trends-bar-chart',
        componentStack: info.componentStack ?? undefined,
    })
}

export function TrendsBarChart({ context }: TrendsBarChartProps): JSX.Element | null {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])
    const { insightProps } = useValues(insightLogic)

    const {
        indexedResults,
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

    const hasData =
        indexedResults &&
        indexedResults[0] &&
        indexedResults[0].data &&
        indexedResults.filter((r: IndexedTrendResult) => r.count !== 0).length > 0

    const buildMeta = useCallback(
        (rr: IndexedTrendResult): TrendsSeriesMeta => ({
            action: rr.action,
            breakdown_value: rr.breakdown_value,
            compare_label: rr.compare_label,
            days: rr.days,
            order: rr.action?.order ?? rr.id,
            filter: rr.filter,
        }),
        []
    )

    const series = useMemo(
        () =>
            buildTrendsBarTimeSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
                getColor: getTrendsColor,
                getHidden: getTrendsHidden,
                buildMeta,
            }),
        [indexedResults, getTrendsColor, getTrendsHidden, buildMeta]
    )
    const labels = currentPeriodResult?.labels ?? []

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

    const chartConfig: BarChartConfig = useMemo(
        () => ({
            showGrid: true,
            tooltip: { pinnable: true, placement: 'top' },
            yScaleType: yAxisScaleType === 'log10' ? 'log' : 'linear',
            axisOrientation: 'vertical',
            barLayout: isPercentStackView ? 'percent' : 'stacked',
            xTickFormatter,
            yTickFormatter,
        }),
        [yAxisScaleType, isPercentStackView, xTickFormatter, yTickFormatter]
    )

    const canHandleClick = !!context?.onDataPointClick || !!hasPersonsModal

    const clickDeps = useMemo<TrendsBarChartClickDeps>(
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

    const onPointClick = useCallback(
        (clickData: PointClickData) => {
            handleTrendsBarChartClick(clickData.series.key, clickData.dataIndex, clickDeps)
        },
        [clickDeps]
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => {
            const onRowClick = canHandleClick
                ? (datum: SeriesDatum) => {
                      const seriesKey = ctx.seriesData[datum.datasetIndex].series.key
                      handleTrendsBarChartClick(seriesKey, datum.dataIndex, clickDeps)
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
        <BarChart<TrendsSeriesMeta>
            series={series}
            labels={labels}
            config={chartConfig}
            theme={theme}
            tooltip={renderTooltip}
            onPointClick={canHandleClick ? onPointClick : undefined}
            className="LineGraph"
            dataAttr="trend-bar-graph"
            onError={handleChartError}
        />
    )
}

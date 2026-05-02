import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo, type ErrorInfo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { BarChart, createXAxisTickCallback } from 'lib/hog-charts'
import type { BarChartConfig, TooltipContext } from 'lib/hog-charts'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { groupsModel } from '~/models/groupsModel'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { trendsDataLogic } from '../../trendsDataLogic'
import type { IndexedTrendResult } from '../../types'
import { buildTrendsYTickFormatter } from '../trends-line-chart/trendsAxisFormat'
import type { TrendsSeriesMeta } from '../trends-line-chart/trendsSeriesMeta'
import { TrendsTooltip } from '../trends-line-chart/TrendsTooltip'
import { buildTrendsBarTimeSeries } from './trendsBarChartTransforms'

interface TrendsBarChartProps {
    context?: QueryContext<InsightVizNode>
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
        getTrendsColor,
        getTrendsHidden,
    } = useValues(trendsDataLogic(insightProps))
    const { timezone, baseCurrency } = useValues(teamLogic)
    const { aggregationLabel } = useValues(groupsModel)

    const isPercentStackView = !!showPercentStackView && !!supportsPercentStackView

    const resolvedGroupTypeLabel = resolveGroupTypeLabel(labelGroupType, aggregationLabel, context?.groupTypeLabel)

    const hasData = !!indexedResults?.[0]?.data && indexedResults.some((r: IndexedTrendResult) => r.count !== 0)

    const series = useMemo(
        () =>
            buildTrendsBarTimeSeries<IndexedTrendResult, TrendsSeriesMeta>(indexedResults ?? [], {
                getColor: getTrendsColor,
                getHidden: getTrendsHidden,
                buildMeta: buildBarMeta,
            }),
        [indexedResults, getTrendsColor, getTrendsHidden]
    )
    const labels = currentPeriodResult?.labels ?? EMPTY_LABELS

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

    const renderTooltip = useCallback(
        (ctx: TooltipContext<TrendsSeriesMeta>) => (
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
            />
        ),
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
            className="BarGraph"
            dataAttr="trend-bar-graph"
            onError={handleChartError}
        />
    )
}

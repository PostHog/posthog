import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { createXAxisTickCallback } from 'lib/charts/utils/dates'
import { buildTheme } from 'lib/charts/utils/theme'
import { LineChart } from 'lib/hog-charts'
import type { LineChartConfig, Series } from 'lib/hog-charts'
import type { TooltipContext } from 'lib/hog-charts/core/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { groupsModel } from '~/models/groupsModel'
import { GoalLine as SchemaGoalLine, InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType } from '~/types'

import { InsightEmptyState } from '../../insights/EmptyStates'
import { trendsDataLogic } from '../trendsDataLogic'
import type { IndexedTrendResult } from '../types'
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
        goalLines,
        getTrendsColor,
        currentPeriodResult,
        breakdownFilter,
        insightData,
        trendsFilter,
        formula,
        isStickiness,
        labelGroupType,
    } = useValues(trendsDataLogic(insightProps))
    const { timezone, baseCurrency } = useValues(teamLogic)
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

    const hogSeries: Series<TrendsSeriesMeta>[] = useMemo(
        () =>
            (indexedResults ?? [])
                .filter((r: IndexedTrendResult) => r.count !== 0)
                .map((r: IndexedTrendResult) => ({
                    key: `${r.id}`,
                    label: r.label ?? '',
                    data: r.data,
                    color: getTrendsColor(r),
                    fillArea: display === ChartDisplayType.ActionsAreaGraph,
                    meta: {
                        action: r.action,
                        breakdown_value: r.breakdown_value,
                        compare_label: r.compare_label,
                        days: r.days,
                        // Fall back to the pre-filter index (r.id) so ordering is stable when earlier series are dropped.
                        order: r.action?.order ?? r.id,
                        filter: r.filter,
                    },
                })),
        [indexedResults, display, getTrendsColor]
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
            goalLines: goalLines?.map((g: SchemaGoalLine) => ({
                value: g.value,
                label: g.label ?? undefined,
                borderColor: g.borderColor ?? undefined,
            })),
        }
    }, [interval, currentPeriodResult?.days, timezone, yAxisScaleType, isPercentStackView, goalLines])

    const formatCompareLabel = context?.formatCompareLabel
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
                formatCompareLabel={formatCompareLabel}
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
            formatCompareLabel,
        ]
    )

    if (!hasData) {
        return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
    }

    return <LineChart series={hogSeries} labels={labels} config={chartConfig} theme={theme} tooltip={renderTooltip} />
}

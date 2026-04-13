import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { createXAxisTickCallback } from 'lib/charts/utils/dates'
import { buildTheme } from 'lib/charts/utils/theme'
import { LineChart } from 'lib/hog-charts'
import type { LineChartConfig, PointClickData, Series } from 'lib/hog-charts'
import type { TooltipContext } from 'lib/hog-charts/core/types'
import { ReferenceLines } from 'lib/hog-charts/overlays/ReferenceLine'
import { hexToRGBA } from 'lib/utils'
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
        goalLines,
        getTrendsColor,
        currentPeriodResult,
        breakdownFilter,
        insightData,
        trendsFilter,
        formula,
        isStickiness,
        labelGroupType,
        hasPersonsModal,
        querySource,
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

    const hogSeries: Series<TrendsSeriesMeta>[] = useMemo(
        () =>
            (indexedResults ?? []).map((r: IndexedTrendResult) => ({
                key: `${r.id}`,
                label: r.label ?? '',
                data: r.data,
                color: r.compare_label === 'previous' ? hexToRGBA(getTrendsColor(r), 0.5) : getTrendsColor(r),
                fillArea: display === ChartDisplayType.ActionsAreaGraph,
                meta: {
                    action: r.action,
                    breakdown_value: r.breakdown_value,
                    compare_label: r.compare_label,
                    days: r.days,
                    // Use action order when available; fall back to the series index for stable ordering.
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
        }
    }, [interval, currentPeriodResult?.days, timezone, yAxisScaleType, isPercentStackView])

    const referenceLines = useMemo(() => goalLinesToReferenceLines(goalLines, hogSeries), [goalLines, hogSeries])

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
        >
            <ReferenceLines lines={referenceLines} />
        </LineChart>
    )
}

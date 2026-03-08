import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { insightAlertsLogic } from 'lib/components/Alerts/insightAlertsLogic'
import { DateDisplay } from 'lib/components/DateDisplay'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { Line } from 'lib/hog-charts'
import type { ClickEvent, LineProps, TooltipContext } from 'lib/hog-charts'
import { useKeyHeld } from 'lib/hooks/useKeyHeld'
import { isMultiSeriesFormula } from 'lib/utils'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { groupsModel } from '~/models/groupsModel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ChartDisplayType, ChartParams } from '~/types'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { InsightEmptyState } from '../../insights/EmptyStates'
import { openPersonsModal } from '../persons-modal/PersonsModal'
import { trendsDataLogic } from '../trendsDataLogic'
import { datasetToActorsQuery } from './datasetToActorsQuery'
import {
    buildGoalLines,
    buildTrendsSeries,
    buildYAxis,
    formatTooltipCount,
    getCompareLabels,
    lifecycleSeriesLabel,
    resolveGroupTypeLabel,
    tooltipPointsToSeriesDatum,
} from './trendsChartUtils'

export function TrendsChart(props: ChartParams): JSX.Element | null {
    return (
        <ErrorBoundary exceptionProps={{ feature: 'TrendsChart' }}>
            <TrendsChartInner {...props} />
        </ErrorBoundary>
    )
}

function TrendsChartInner({
    showPersonsModal = true,
    context,
}: ChartParams): JSX.Element | null {
    const { insightProps, insight } = useValues(insightLogic)

    const {
        indexedResults,
        labelGroupType,
        incompletenessOffsetFromEnd,
        formula,
        display,
        interval,
        showValuesOnSeries,
        showPercentStackView,
        supportsPercentStackView,
        trendsFilter,
        lifecycleFilter,
        isLifecycle,
        isStickiness,
        hasDataWarehouseSeries,
        querySource,
        yAxisScaleType,
        showMultipleYAxes,
        goalLines: schemaGoalLines,
        insightData,
        showConfidenceIntervals,
        confidenceLevel,
        showTrendLines,
        showMovingAverage,
        movingAverageIntervals,
        getTrendsColor,
        getTrendsHidden,
        hoveredDatasetIndex,
    } = useValues(trendsDataLogic(insightProps))

    const { setHoveredDatasetIndex } = useActions(trendsDataLogic(insightProps))
    const { weekStartDay, timezone } = useValues(teamLogic)
    const { breakdownFilter } = useValues(insightVizDataLogic(insightProps))
    const { aggregationLabel } = useValues(groupsModel)

    const { alertThresholdLines } = useValues(
        insightAlertsLogic({ insightId: insight.id!, insightLogicProps: insightProps })
    )

    const isShiftPressed = useKeyHeld('Shift')

    useEffect(() => {
        if (!isShiftPressed) {
            setHoveredDatasetIndex(null)
        }
    }, [isShiftPressed, setHoveredDatasetIndex])

    const isBar =
        display === ChartDisplayType.ActionsBar || display === ChartDisplayType.ActionsUnstackedBar || isLifecycle
    const isArea = display === ChartDisplayType.ActionsAreaGraph
    const isStacked = isLifecycle ? (lifecycleFilter?.stacked ?? true) : display !== ChartDisplayType.ActionsUnstackedBar
    const isPercentStackView = !!supportsPercentStackView && !!showPercentStackView
    const isLog10 = yAxisScaleType === 'log10'
    const isInProgress = !isStickiness && incompletenessOffsetFromEnd < 0
    const isHighlightBarMode = isBar && isStacked && isShiftPressed

    const labels = getCompareLabels(indexedResults)

    const series = useMemo(
        () =>
            buildTrendsSeries({
                indexedResults,
                isBar,
                isArea,
                isLog10,
                isStickiness,
                showMultipleYAxes,
                showTrendLines,
                showConfidenceIntervals,
                confidenceLevel,
                showMovingAverage,
                movingAverageIntervals,
                getTrendsColor,
                getTrendsHidden,
            }),
        [
            indexedResults,
            isBar,
            isArea,
            isLog10,
            isStickiness,
            showMultipleYAxes,
            showTrendLines,
            showConfidenceIntervals,
            confidenceLevel,
            showMovingAverage,
            movingAverageIntervals,
            getTrendsColor,
            getTrendsHidden,
        ]
    )

    if (
        !(indexedResults && indexedResults[0]?.data && indexedResults.filter((r) => r.count !== 0).length > 0)
    ) {
        return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
    }

    const goalLines = buildGoalLines(alertThresholdLines, schemaGoalLines ?? undefined)
    const yAxis = buildYAxis(isLog10, isPercentStackView, showMultipleYAxes ?? null, series.length)

    const canClick =
        !!context?.onDataPointClick ||
        (showPersonsModal && !isMultiSeriesFormula(formula) && !hasDataWarehouseSeries)

    const groupTypeLabel = resolveGroupTypeLabel(context?.groupTypeLabel, labelGroupType, aggregationLabel)

    function renderSeriesLabel(value: React.ReactNode, datum: SeriesDatum): React.ReactNode {
        if (isLifecycle) {
            return lifecycleSeriesLabel(datum)
        }
        const hasBreakdown = datum.breakdown_value !== undefined && !!datum.breakdown_value
        return (
            <div className="datum-label-column">
                {!formula && (
                    <SeriesLetter
                        className="mr-2"
                        hasBreakdown={hasBreakdown}
                        seriesIndex={datum.action?.order ?? datum.id}
                        seriesColor={datum.color}
                    />
                )}
                {value}
            </div>
        )
    }

    function renderTooltip(ctx: TooltipContext): React.ReactNode {
        const seriesData = tooltipPointsToSeriesDatum(ctx.points)
        const referencePoint = ctx.points[0]
        const date = (referencePoint?.meta?.days as string[])?.[referencePoint?.pointIndex] as string | undefined

        return (
            <InsightTooltip
                date={date}
                timezone={timezone}
                seriesData={seriesData}
                breakdownFilter={breakdownFilter}
                interval={interval}
                dateRange={insightData?.resolved_date_range}
                showShiftKeyHint={isBar && isStacked && !isHighlightBarMode}
                renderSeries={renderSeriesLabel}
                renderCount={(value: number) =>
                    formatTooltipCount(value, { isStickiness, isPercentStackView, trendsFilter, indexedResults, seriesData })
                }
                hideInspectActorsSection={!showPersonsModal}
                groupTypeLabel={groupTypeLabel}
                {...(isLifecycle ? { altTitle: 'Users', altRightTitle: (_, d) => d } : {})}
            />
        )
    }

    function handleClick(event: ClickEvent): void {
        if (!event.meta) {
            return
        }

        const dataset = event.meta._dataset as (typeof indexedResults)[number] | undefined
        if (!dataset) {
            return
        }

        const day = dataset.action?.days?.[event.pointIndex] ?? dataset.days?.[event.pointIndex] ?? ''
        const label = dataset.label ?? dataset.labels?.[event.pointIndex] ?? ''

        if (context?.onDataPointClick) {
            context.onDataPointClick(
                {
                    breakdown: (dataset as any).breakdownValues?.[event.pointIndex],
                    compare: (dataset as any).compareLabels?.[event.pointIndex] || undefined,
                    day,
                },
                indexedResults[0]
            )
            return
        }

        if (!showPersonsModal || isMultiSeriesFormula(formula) || hasDataWarehouseSeries) {
            return
        }

        const title = isStickiness ? (
            <>
                <PropertyKeyInfo value={label || ''} disablePopover /> stickiness on {interval || 'day'} {day}
            </>
        ) : (
            (titleLabel: string) => (
                <>
                    {titleLabel} on{' '}
                    <DateDisplay
                        interval={interval || 'day'}
                        resolvedDateRange={insightData?.resolved_date_range}
                        timezone={timezone}
                        weekStartDay={weekStartDay}
                        date={day?.toString() || ''}
                    />
                </>
            )
        )

        openPersonsModal({
            title,
            query: datasetToActorsQuery({ dataset, query: querySource!, day }),
            additionalSelect:
                isLifecycle || isStickiness
                    ? {}
                    : {
                          value_at_data_point: 'event_count',
                          matched_recordings: 'matched_recordings',
                      },
            orderBy: isLifecycle || isStickiness ? undefined : ['event_count DESC, actor_id DESC'],
        })
    }

    const lineProps: LineProps = {
        data: series,
        labels,
        yAxis,
        goalLines,
        className: 'TrendsChart w-full grow relative overflow-hidden',
        stacked: isStacked,
        stacked100: isPercentStackView,
        isArea,
        fillOpacity: isPercentStackView ? 1 : 0.5,
        crosshair: !isBar,
        incompletenessOffset:
            isInProgress && incompletenessOffsetFromEnd < 0 ? Math.abs(incompletenessOffsetFromEnd) : 0,
        hideXAxis: false,
        hideYAxis: false,
        showValues: !!showValuesOnSeries,
        maxSeries: 50,
        tooltip: { shared: true, render: renderTooltip },
        onClick: canClick ? handleClick : undefined,
        highlightSeriesIndex: isHighlightBarMode ? hoveredDatasetIndex : null,
        onHighlightChange: isHighlightBarMode
            ? (idx) => setHoveredDatasetIndex(idx)
            : undefined,
        days: indexedResults[0]?.days,
        interval: interval ?? undefined,
        timezone,
    }

    return <Line {...lineProps} />
}

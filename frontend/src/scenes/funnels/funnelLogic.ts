import { kea } from 'kea'
import equal from 'fast-deep-equal'
import { insightLogic } from 'scenes/insights/insightLogic'
import { average, percentage, sum } from 'lib/utils'
import type { funnelLogicType } from './funnelLogicType'
import {
    BinCountValue,
    FilterType,
    FlattenedFunnelStepByBreakdown,
    FunnelResultType,
    FunnelConversionWindowTimeUnit,
    FunnelCorrelation,
    FunnelCorrelationResultsType,
    FunnelsFilterType,
    FunnelStep,
    FunnelStepRangeEntityFilter,
    FunnelStepReference,
    FunnelStepWithConversionMetrics,
    FunnelStepWithNestedBreakdown,
    FunnelsTimeConversionBins,
    FunnelTimeConversionMetrics,
    FunnelVizType,
    HistogramGraphDatum,
    InsightLogicProps,
    InsightType,
    StepOrderValue,
    TrendResult,
} from '~/types'
import { BIN_COUNT_AUTO } from 'lib/constants'

import {
    aggregateBreakdownResult,
    getBreakdownStepValues,
    getClampedStepRangeFilter,
    getIncompleteConversionWindowStartDate,
    getLastFilledStep,
    getReferenceStep,
    getVisibilityKey,
    isBreakdownFunnelResults,
    isStepsEmpty,
    isValidBreakdownParameter,
    stepsWithConversionMetrics,
    flattenedStepsByBreakdown,
    generateBaselineConversionUrl,
    parseBreakdownValue,
    parseEventAndProperty,
} from './funnelUtils'
import { dashboardsModel } from '~/models/dashboardsModel'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { isFunnelsFilter, keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { groupsModel, Noun } from '~/models/groupsModel'
import { dayjs } from 'lib/dayjs'
import { LemonSelectOptions } from 'lib/lemon-ui/LemonSelect'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { funnelTitle } from 'scenes/trends/persons-modal/persons-modal-utils'

export type OpenPersonsModelProps = {
    step: FunnelStep
    stepIndex?: number
    converted: boolean
}

export const funnelLogic = kea<funnelLogicType>({
    path: (key) => ['scenes', 'funnels', 'funnelLogic', key],
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('insight_funnel'),

    connect: (props: InsightLogicProps) => ({
        values: [
            insightLogic(props),
            ['filters as inflightFilters', 'insight', 'isInDashboardContext', 'hiddenLegendKeys'],
            groupsModel,
            ['aggregationLabel'],
        ],
        actions: [insightLogic(props), ['loadResults', 'loadResultsSuccess', 'toggleVisibility']],
        logic: [dashboardsModel],
    }),

    actions: () => ({
        clearFunnel: true,
        setFilters: (
            filters: Partial<FunnelsFilterType>,
            refresh: boolean = false,
            mergeWithExisting: boolean = true
        ) => ({
            filters,
            refresh,
            mergeWithExisting,
        }),
        setEventExclusionFilters: (filters: Partial<FilterType>) => ({ filters }),
        setOneEventExclusionFilter: (eventFilter: FunnelStepRangeEntityFilter, index: number) => ({
            eventFilter,
            index,
        }),
        saveFunnelInsight: (name: string) => ({ name }),
        openPersonsModalForStep: ({ step, stepIndex, converted }: OpenPersonsModelProps) => ({
            step,
            stepIndex,
            converted,
        }),
        openPersonsModalForSeries: ({
            step,
            series,
            converted,
        }: {
            step: FunnelStep
            series: Omit<FunnelStepWithConversionMetrics, 'nested_breakdown'>
            converted: boolean
        }) => ({
            step,
            series,
            converted,
        }),
        setStepReference: (stepReference: FunnelStepReference) => ({ stepReference }),
        changeStepRange: (funnel_from_step?: number, funnel_to_step?: number) => ({
            funnel_from_step,
            funnel_to_step,
        }),
        setIsGroupingOutliers: (isGroupingOutliers) => ({ isGroupingOutliers }),
        setBinCount: (binCount: BinCountValue) => ({ binCount }),
        toggleAdvancedMode: true,

        showTooltip: (
            origin: [number, number, number],
            stepIndex: number,
            series: FunnelStepWithConversionMetrics
        ) => ({
            origin,
            stepIndex,
            series,
        }),
        hideTooltip: true,

        // Correlation related actions
        hideSkewWarning: true,
        openCorrelationPersonsModal: (correlation: FunnelCorrelation, success: boolean) => ({
            correlation,
            success,
        }),
    }),
    reducers: ({ props }) => ({
        people: {
            clearFunnel: () => [],
        },
        isGroupingOutliers: [
            true,
            {
                setIsGroupingOutliers: (_, { isGroupingOutliers }) => isGroupingOutliers,
            },
        ],
        error: [
            null as any,
            {
                [insightLogic(props).actionTypes.startQuery]: () => null,
                [insightLogic(props).actionTypes.endQuery]: (_: any, { exception }: any) => exception ?? null,
                [insightLogic(props).actionTypes.abortQuery]: (_: any, { exception }: any) => exception ?? null,
            },
        ],
        skewWarningHidden: [
            false,
            {
                hideSkewWarning: () => true,
            },
        ],
        isTooltipShown: [
            false,
            {
                showTooltip: () => true,
                hideTooltip: () => false,
            },
        ],
        currentTooltip: [
            null as [number, FunnelStepWithConversionMetrics] | null,
            {
                showTooltip: (_, { stepIndex, series }) => [stepIndex, series],
            },
        ],
        tooltipOrigin: [
            null as [number, number, number] | null, // x, y, width
            {
                showTooltip: (_, { origin }) => origin,
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        filters: [
            (s) => [s.inflightFilters],
            (inflightFilters): Partial<FunnelsFilterType> =>
                inflightFilters && isFunnelsFilter(inflightFilters) ? inflightFilters : {},
        ],
        loadedFilters: [
            (s) => [s.insight],
            ({ filters }): Partial<FunnelsFilterType> => (filters && isFunnelsFilter(filters) ? filters : {}),
        ],
        stepReference: [
            (s) => [s.filters],
            ({ funnel_step_reference }) => funnel_step_reference || FunnelStepReference.total,
        ],
        results: [
            (s) => [s.insight],
            ({ filters, result }): FunnelResultType => {
                if (filters?.insight === InsightType.FUNNELS) {
                    if (Array.isArray(result) && Array.isArray(result[0]) && result[0][0].breakdowns) {
                        // in order to stop the UI having to check breakdowns and breakdown
                        // this collapses breakdowns onto the breakdown property
                        return result.map((series) =>
                            series.map((r: { [x: string]: any; breakdowns: any; breakdown_value: any }) => {
                                const { breakdowns, breakdown_value, ...singlePropertyClone } = r
                                singlePropertyClone.breakdown = breakdowns
                                singlePropertyClone.breakdown_value = breakdown_value
                                return singlePropertyClone
                            })
                        )
                    }
                    return result
                } else {
                    return []
                }
            },
        ],
        conversionWindow: [
            (s) => [s.filters],
            ({ funnel_window_interval, funnel_window_interval_unit }) => ({
                funnel_window_interval: funnel_window_interval || 14,
                funnel_window_interval_unit: funnel_window_interval_unit || FunnelConversionWindowTimeUnit.Day,
            }),
        ],
        timeConversionResults: [
            (s) => [s.results, s.filters],
            (results, filters): FunnelsTimeConversionBins | null => {
                return filters.funnel_viz_type === FunnelVizType.TimeToConvert
                    ? (results as FunnelsTimeConversionBins)
                    : null
            },
        ],
        isStepsEmpty: [() => [selectors.filters], (filters: FunnelsFilterType) => isStepsEmpty(filters)],
        propertiesForUrl: [() => [selectors.filters], (filters: FunnelsFilterType) => cleanFilters(filters)],
        hasFunnelResults: [
            () => [selectors.filters, selectors.steps, selectors.histogramGraphData],
            (filters, steps, histogramGraphData) => {
                if (filters.funnel_viz_type === FunnelVizType.Steps || !filters.funnel_viz_type) {
                    return !!(steps && steps[0] && steps[0].count > -1)
                }
                if (filters.funnel_viz_type === FunnelVizType.TimeToConvert) {
                    return (histogramGraphData?.length ?? 0) > 0
                }
                if (filters.funnel_viz_type === FunnelVizType.Trends) {
                    return (steps?.length ?? 0) > 0 && steps?.[0]?.labels
                }
                return false
            },
        ],
        filtersDirty: [
            () => [selectors.filters, selectors.loadedFilters],
            (filters, lastFilters): boolean => !equal(cleanFilters(filters), cleanFilters(lastFilters)),
        ],
        histogramGraphData: [
            () => [selectors.timeConversionResults],
            (timeConversionResults: FunnelsTimeConversionBins): HistogramGraphDatum[] | null => {
                if ((timeConversionResults?.bins?.length ?? 0) < 2) {
                    return null // There are no results
                }
                const binSize = timeConversionResults.bins[1][0] - timeConversionResults.bins[0][0]
                const totalCount = sum(timeConversionResults.bins.map(([, count]) => count))
                if (totalCount === 0) {
                    return [] // Nobody has converted in the time period
                }
                return timeConversionResults.bins.map(([id, count]: [id: number, count: number]) => {
                    const value = Math.max(0, id)
                    const percent = count / totalCount
                    return {
                        id: value,
                        bin0: value,
                        bin1: value + binSize,
                        count,
                        label: percent === 0 ? '' : percentage(percent, 1, true),
                    }
                })
            },
        ],
        isFunnelWithEnoughSteps: [
            () => [selectors.numberOfSeries],
            (numberOfSeries) => {
                return numberOfSeries > 1
            },
        ],
        numberOfSeries: [
            () => [selectors.filters],
            (filters): number => (filters.events?.length || 0) + (filters.actions?.length || 0),
        ],
        conversionMetrics: [
            () => [selectors.steps, selectors.loadedFilters, selectors.timeConversionResults],
            (steps, loadedFilters, timeConversionResults): FunnelTimeConversionMetrics => {
                // steps should be empty in time conversion view. Return metrics precalculated on backend
                if (loadedFilters.funnel_viz_type === FunnelVizType.TimeToConvert) {
                    return {
                        averageTime: timeConversionResults?.average_conversion_time ?? 0,
                        stepRate: 0,
                        totalRate: 0,
                    }
                }

                // Handle metrics for trends
                if (loadedFilters.funnel_viz_type === FunnelVizType.Trends) {
                    return {
                        averageTime: 0,
                        stepRate: 0,
                        totalRate: average((steps?.[0] as unknown as TrendResult)?.data ?? []) / 100,
                    }
                }

                // Handle metrics for steps
                // no concept of funnel_from_step and funnel_to_step here
                if (steps.length <= 1) {
                    return {
                        averageTime: 0,
                        stepRate: 0,
                        totalRate: 0,
                    }
                }

                const toStep = getLastFilledStep(steps)
                const fromStep = getReferenceStep(steps, FunnelStepReference.total)

                return {
                    averageTime: steps.reduce(
                        (conversion_time, step) => conversion_time + (step.average_conversion_time || 0),
                        0
                    ),
                    stepRate: toStep.count / fromStep.count,
                    totalRate: steps[steps.length - 1].count / steps[0].count,
                }
            },
        ],
        isSkewed: [
            (s) => [s.conversionMetrics, s.skewWarningHidden],
            (conversionMetrics, skewWarningHidden): boolean => {
                return !skewWarningHidden && (conversionMetrics.totalRate < 0.1 || conversionMetrics.totalRate > 0.9)
            },
        ],
        apiParams: [
            (s) => [s.filters],
            (filters) => {
                /* TODO: Related to #4329. We're mixing `from_dashboard` as both which causes hard to manage code:
                    a) a boolean-based hash param to determine if the insight is saved in a dashboard (when viewing insights page)
                    b) dashboard ID passed as a filter in certain kind of insights when viewing in the dashboard page
                */
                const { from_dashboard } = filters
                const cleanedParams: Partial<FunnelsFilterType> = cleanFilters(filters)
                return {
                    ...(from_dashboard ? { from_dashboard } : {}),
                    ...cleanedParams,
                }
            },
        ],
        filterSteps: [
            () => [selectors.apiParams],
            (apiParams) =>
                [...(apiParams.events ?? []), ...(apiParams.actions ?? []), ...(apiParams.new_entity ?? [])].sort(
                    (a, b) => a.order - b.order
                ),
        ],
        eventCount: [() => [selectors.apiParams], (apiParams) => apiParams.events?.length || 0],
        actionCount: [() => [selectors.apiParams], (apiParams) => apiParams.actions?.length || 0],
        interval: [() => [selectors.apiParams], (apiParams) => apiParams.interval || ''],
        steps: [
            (s) => [s.filters, s.results, s.apiParams],
            (
                filters: Partial<FunnelsFilterType>,
                results: FunnelResultType,
                apiParams
            ): FunnelStepWithNestedBreakdown[] => {
                const stepResults =
                    filters.funnel_viz_type !== FunnelVizType.TimeToConvert
                        ? (results as FunnelStep[] | FunnelStep[][])
                        : []

                if (!Array.isArray(stepResults)) {
                    return []
                }

                let stepsWithNestedBreakdown: FunnelStepWithNestedBreakdown[] = []
                if (
                    isBreakdownFunnelResults(results) &&
                    isValidBreakdownParameter(apiParams.breakdown, apiParams.breakdowns)
                ) {
                    const breakdownProperty = apiParams.breakdowns
                        ? apiParams.breakdowns.map((b) => b.property).join('::')
                        : apiParams.breakdown ?? undefined
                    stepsWithNestedBreakdown = aggregateBreakdownResult(results, breakdownProperty).sort(
                        (a, b) => a.order - b.order
                    )
                }

                return !!filters.breakdowns || !!filters.breakdown
                    ? stepsWithNestedBreakdown
                    : ([...stepResults] as FunnelStep[]).sort((a, b) => a.order - b.order)
            },
        ],
        stepsWithConversionMetrics: [
            () => [selectors.steps, selectors.stepReference],
            (steps, stepReference): FunnelStepWithConversionMetrics[] => {
                return stepsWithConversionMetrics(steps, stepReference)
            },
        ],
        visibleStepsWithConversionMetrics: [
            (s) => [s.stepsWithConversionMetrics, s.hiddenLegendKeys, s.flattenedStepsByBreakdown, s.isOnlySeries],
            (steps, hiddenLegendKeys, flattenedStepsByBreakdown, isOnlySeries): FunnelStepWithConversionMetrics[] => {
                const baseLineSteps = flattenedStepsByBreakdown.find((b) => b.isBaseline)
                return steps.map((step, stepIndex) => ({
                    ...step,
                    nested_breakdown: (!!baseLineSteps?.steps
                        ? [baseLineSteps.steps[stepIndex], ...(step?.nested_breakdown ?? [])]
                        : step?.nested_breakdown
                    )
                        ?.map((b, breakdownIndex) => ({
                            ...b,
                            order: breakdownIndex,
                        }))
                        ?.filter((b) => isOnlySeries || !hiddenLegendKeys[getVisibilityKey(b.breakdown_value)]),
                }))
            },
        ],
        flattenedStepsByBreakdown: [
            () => [selectors.stepsWithConversionMetrics, selectors.filters, selectors.disableFunnelBreakdownBaseline],
            (steps, filters, disableBaseline): FlattenedFunnelStepByBreakdown[] => {
                return flattenedStepsByBreakdown(steps, filters.layout, disableBaseline)
            },
        ],
        flattenedBreakdowns: [
            () => [selectors.flattenedStepsByBreakdown],
            (breakdowns): FlattenedFunnelStepByBreakdown[] => {
                return breakdowns.filter((b) => b.breakdown)
            },
        ],
        isOnlySeries: [
            (s) => [s.flattenedBreakdowns],
            (flattenedBreakdowns): boolean => flattenedBreakdowns.length <= 1,
        ],
        numericBinCount: [
            () => [selectors.filters, selectors.timeConversionResults],
            (filters, timeConversionResults): number => {
                if (filters.bin_count === BIN_COUNT_AUTO) {
                    return timeConversionResults?.bins?.length ?? 0
                }
                return filters.bin_count ?? 0
            },
        ],
        exclusionDefaultStepRange: [
            () => [selectors.numberOfSeries, selectors.isFunnelWithEnoughSteps],
            (numberOfSeries, isFunnelWithEnoughSteps): Omit<FunnelStepRangeEntityFilter, 'id' | 'name'> => ({
                funnel_from_step: 0,
                funnel_to_step: isFunnelWithEnoughSteps ? numberOfSeries - 1 : 1,
            }),
        ],
        exclusionFilters: [
            () => [selectors.filters],
            (filters): FilterType => ({
                events: filters.exclusions,
            }),
        ],
        areExclusionFiltersValid: [
            () => [selectors.error],
            (e: any): boolean => {
                return !(e?.status === 400 && e?.type === 'validation_error')
            },
        ],
        disableFunnelBreakdownBaseline: [
            () => [(_, props) => props],
            (props: InsightLogicProps): boolean => !!props.cachedInsight?.disable_baseline,
        ],
        aggregationTargetLabel: [
            (s) => [s.filters, s.aggregationLabel],
            (filters, aggregationLabel): Noun =>
                filters.funnel_aggregate_by_hogql
                    ? aggregationLabelForHogQL(filters.funnel_aggregate_by_hogql)
                    : aggregationLabel(filters.aggregation_group_type_index),
        ],
        advancedOptionsUsedCount: [
            (s) => [s.filters, s.stepReference],
            (filters, stepReference): number => {
                let count = 0
                if (filters.funnel_order_type && filters.funnel_order_type !== StepOrderValue.ORDERED) {
                    count = count + 1
                }
                if (stepReference !== FunnelStepReference.total) {
                    count = count + 1
                }
                if (filters.exclusions?.length) {
                    count = count + 1
                }
                return count
            },
        ],
        incompletenessOffsetFromEnd: [
            (s) => [s.steps, s.conversionWindow],
            (steps, conversionWindow) => {
                // Returns negative number of points to paint over starting from end of array
                if (steps?.[0]?.days === undefined) {
                    return 0
                }
                const startDate = getIncompleteConversionWindowStartDate(conversionWindow)
                const startIndex = steps[0].days.findIndex((day) => dayjs(day) >= startDate)

                if (startIndex !== undefined && startIndex !== -1) {
                    return startIndex - steps[0].days.length
                } else {
                    return 0
                }
            },
        ],
        breakdownAttributionStepOptions: [
            (s) => [s.steps],
            (steps): LemonSelectOptions<number> => steps.map((_, idx) => ({ value: idx, label: `Step ${idx + 1}` })),
        ],
    }),

    listeners: ({ actions, values, props }) => ({
        setStepReference: ({ stepReference }) => {
            if (stepReference !== values.filters.funnel_step_reference) {
                actions.setFilters({ funnel_step_reference: stepReference }, true, true)
            }
        },
        setFilters: ({ filters, mergeWithExisting }) => {
            const cleanedParams = cleanFilters(
                mergeWithExisting
                    ? {
                          ...values.filters,
                          ...filters,
                      }
                    : filters,
                values.filters
            )
            insightLogic(props).actions.setFilters(cleanedParams)
        },
        setEventExclusionFilters: ({ filters }) => {
            const exclusions = (filters.events as FunnelStepRangeEntityFilter[]).map((exclusion) => {
                exclusion.funnel_from_step =
                    exclusion.funnel_from_step || values.exclusionDefaultStepRange.funnel_from_step
                exclusion.funnel_to_step = exclusion.funnel_to_step || values.exclusionDefaultStepRange.funnel_to_step
                return exclusion
            })
            actions.setFilters({
                ...values.filters,
                exclusions,
            })
        },
        setOneEventExclusionFilter: ({ eventFilter, index }) => {
            actions.setFilters({
                ...values.filters,
                exclusions: values.filters.exclusions
                    ? values.filters.exclusions.map((e, e_i) =>
                          e_i === index
                              ? getClampedStepRangeFilter({ stepRange: eventFilter, filters: values.filters })
                              : e
                      )
                    : [],
            })
        },
        clearFunnel: ({}) => {
            actions.setFilters({ new_entity: values.filters.new_entity }, false, true)
        },
        openPersonsModalForStep: ({ step, stepIndex, converted }) => {
            if (values.isInDashboardContext) {
                return
            }

            openPersonsModal({
                // openPersonsModalForStep is for the baseline - for breakdown series use openPersonsModalForSeries
                url: generateBaselineConversionUrl(converted ? step.converted_people_url : step.dropped_people_url),
                title: funnelTitle({
                    converted,
                    // Note - when in a legend the step.order is always 0 so we use stepIndex instead
                    step: typeof stepIndex === 'number' ? stepIndex + 1 : step.order + 1,
                    label: step.name,
                    seriesId: step.order,
                    order_type: values.filters.funnel_order_type,
                }),
            })
        },
        openPersonsModalForSeries: ({ step, series, converted }) => {
            if (values.isInDashboardContext) {
                return
            }
            // Version of openPersonsModalForStep that accurately handles breakdown series
            const breakdownValues = getBreakdownStepValues(series, series.order)
            openPersonsModal({
                url: converted ? series.converted_people_url : series.dropped_people_url,
                title: funnelTitle({
                    converted,
                    step: step.order + 1,
                    breakdown_value: breakdownValues.isEmpty ? undefined : breakdownValues.breakdown_value.join(', '),
                    label: step.name,
                    seriesId: step.order,
                    order_type: values.filters.funnel_order_type,
                }),
            })
        },
        openCorrelationPersonsModal: ({ correlation, success }) => {
            if (values.isInDashboardContext) {
                return
            }

            if (correlation.result_type === FunnelCorrelationResultsType.Properties) {
                const { breakdown, breakdown_value } = parseBreakdownValue(correlation.event.event)
                openPersonsModal({
                    url: success ? correlation.success_people_url : correlation.failure_people_url,
                    title: funnelTitle({
                        converted: success,
                        step: values.steps.length,
                        breakdown_value,
                        label: breakdown,
                    }),
                })
            } else {
                const { name } = parseEventAndProperty(correlation.event)

                openPersonsModal({
                    url: success ? correlation.success_people_url : correlation.failure_people_url,
                    title: funnelTitle({
                        converted: success,
                        step: values.steps.length,
                        label: name,
                    }),
                })
            }
        },
        changeStepRange: ({ funnel_from_step, funnel_to_step }) => {
            actions.setFilters({
                funnel_from_step,
                funnel_to_step,
            })
        },
        setBinCount: async ({ binCount }) => {
            actions.setFilters({ bin_count: binCount && binCount !== BIN_COUNT_AUTO ? binCount : undefined })
        },
        setConversionWindow: async () => {
            actions.setFilters(values.conversionWindow)
        },
        toggleAdvancedMode: () => {
            actions.setFilters({ funnel_advanced: !values.filters.funnel_advanced })
        },
    }),
})
function aggregationLabelForHogQL(funnel_aggregate_by_hogql: string): Noun {
    if (funnel_aggregate_by_hogql === 'properties.$session_id') {
        return { singular: 'session', plural: 'sessions' }
    }
    return { singular: 'match', plural: 'matches' }
}

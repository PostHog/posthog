import { kea, path, props, key, connect, selectors, actions, reducers } from 'kea'
import {
    FilterType,
    FunnelResultType,
    FunnelVizType,
    FunnelStep,
    FunnelExclusion,
    FunnelStepReference,
    FunnelStepWithNestedBreakdown,
    InsightLogicProps,
    StepOrderValue,
    FunnelStepWithConversionMetrics,
    FlattenedFunnelStepByBreakdown,
    FunnelsTimeConversionBins,
    HistogramGraphDatum,
    FunnelAPIResponse,
    FunnelTimeConversionMetrics,
    TrendResult,
    FunnelConversionWindowTimeUnit,
    FunnelConversionWindow,
} from '~/types'
import { FunnelsQuery, NodeKind } from '~/queries/schema'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { groupsModel, Noun } from '~/models/groupsModel'

import type { funnelDataLogicType } from './funnelDataLogicType'
import { isFunnelsQuery } from '~/queries/utils'
import { percentage, sum, average } from 'lib/utils'
import { dayjs } from 'lib/dayjs'
import {
    aggregateBreakdownResult,
    aggregationLabelForHogQL,
    flattenedStepsByBreakdown,
    getIncompleteConversionWindowStartDate,
    getLastFilledStep,
    getReferenceStep,
    getVisibilityKey,
    isBreakdownFunnelResults,
    stepsWithConversionMetrics,
} from './funnelUtils'
import { BIN_COUNT_AUTO } from 'lib/constants'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

const DEFAULT_FUNNEL_LOGIC_KEY = 'default_funnel_key'

export const funnelDataLogic = kea<funnelDataLogicType>([
    path((key) => ['scenes', 'funnels', 'funnelDataLogic', key]),
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_FUNNEL_LOGIC_KEY)),

    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            [
                'querySource as vizQuerySource',
                'insightFilter',
                'funnelsFilter',
                'breakdown',
                'series',
                'interval',
                'insightData',
                'insightDataError',
            ],
            groupsModel,
            ['aggregationLabel'],
        ],
        actions: [insightVizDataLogic(props), ['updateInsightFilter', 'updateQuerySource']],
    })),

    actions({
        hideSkewWarning: true,
    }),

    reducers({
        skewWarningHidden: [
            false,
            {
                hideSkewWarning: () => true,
            },
        ],
    }),

    selectors(() => ({
        querySource: [
            (s) => [s.vizQuerySource],
            (vizQuerySource) => (isFunnelsQuery(vizQuerySource) ? vizQuerySource : null),
        ],

        isStepsFunnel: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): boolean | null => {
                return funnelsFilter === null
                    ? null
                    : funnelsFilter === undefined
                    ? true
                    : funnelsFilter.funnel_viz_type === FunnelVizType.Steps
            },
        ],
        isTimeToConvertFunnel: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): boolean | null => {
                return funnelsFilter === null ? null : funnelsFilter?.funnel_viz_type === FunnelVizType.TimeToConvert
            },
        ],
        isTrendsFunnel: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): boolean | null => {
                return funnelsFilter === null ? null : funnelsFilter?.funnel_viz_type === FunnelVizType.Trends
            },
        ],

        isEmptyFunnel: [
            (s) => [s.querySource],
            (q): boolean | null => {
                return isFunnelsQuery(q)
                    ? q.series.filter((n) => n.kind === NodeKind.EventsNode || n.kind === NodeKind.ActionsNode)
                          .length === 0
                    : null
            },
        ],

        aggregationTargetLabel: [
            (s) => [s.querySource, s.aggregationLabel],
            (querySource, aggregationLabel): Noun => {
                if (!querySource) {
                    return { singular: '', plural: '' }
                }

                return querySource.funnelsFilter?.funnel_aggregate_by_hogql
                    ? aggregationLabelForHogQL(querySource.funnelsFilter.funnel_aggregate_by_hogql)
                    : aggregationLabel(querySource.aggregation_group_type_index)
            },
        ],

        results: [
            (s) => [s.insightData],
            (insightData: FunnelAPIResponse | null): FunnelResultType => {
                // TODO: after hooking up data manager, check that we have a funnels result here
                if (insightData?.result) {
                    if (isBreakdownFunnelResults(insightData.result) && insightData.result?.[0]?.[0]?.breakdowns) {
                        // in order to stop the UI having to check breakdowns and breakdown
                        // this collapses breakdowns onto the breakdown property
                        return insightData.result.map((series) =>
                            series.map((step) => {
                                const { breakdowns, ...clone } = step
                                clone.breakdown = breakdowns as (string | number)[]
                                return clone
                            })
                        )
                    }
                    return insightData.result
                } else {
                    return []
                }
            },
        ],
        isFunnelWithEnoughSteps: [
            (s) => [s.series],
            (series) => {
                return (series?.length || 0) > 1
            },
        ],
        steps: [
            (s) => [s.breakdown, s.results, s.isTimeToConvertFunnel],
            (breakdown, results, isTimeToConvertFunnel): FunnelStepWithNestedBreakdown[] => {
                // we need to check wether results are an array, since isTimeToConvertFunnel can be false,
                // while still having "time-to-convert" results in insightData
                if (!isTimeToConvertFunnel && Array.isArray(results)) {
                    if (isBreakdownFunnelResults(results)) {
                        const breakdownProperty = breakdown?.breakdowns
                            ? breakdown?.breakdowns.map((b) => b.property).join('::')
                            : breakdown?.breakdown ?? undefined
                        return aggregateBreakdownResult(results, breakdownProperty).sort((a, b) => a.order - b.order)
                    }
                    return (results as FunnelStep[]).sort((a, b) => a.order - b.order)
                } else {
                    return []
                }
            },
        ],
        stepsWithConversionMetrics: [
            (s) => [s.steps, s.funnelsFilter],
            (steps, funnelsFilter): FunnelStepWithConversionMetrics[] => {
                const stepReference = funnelsFilter?.funnel_step_reference || FunnelStepReference.total
                return stepsWithConversionMetrics(steps, stepReference)
            },
        ],

        // hack for experiments to remove displaying baseline from the funnel viz
        disableFunnelBreakdownBaseline: [
            () => [(_, props) => props],
            (props: InsightLogicProps): boolean => !!props.cachedInsight?.disable_baseline,
        ],
        flattenedBreakdowns: [
            (s) => [s.stepsWithConversionMetrics, s.funnelsFilter, s.disableFunnelBreakdownBaseline],
            (steps, funnelsFilter, disableBaseline): FlattenedFunnelStepByBreakdown[] => {
                return flattenedStepsByBreakdown(steps, funnelsFilter?.layout, disableBaseline, true)
            },
        ],
        visibleStepsWithConversionMetrics: [
            (s) => [s.stepsWithConversionMetrics, s.funnelsFilter, s.flattenedBreakdowns],
            (steps, funnelsFilter, flattenedBreakdowns): FunnelStepWithConversionMetrics[] => {
                const isOnlySeries = flattenedBreakdowns.length <= 1
                const baseLineSteps = flattenedBreakdowns.find((b) => b.isBaseline)
                return steps.map((step, stepIndex) => ({
                    ...step,
                    nested_breakdown: (baseLineSteps?.steps
                        ? [baseLineSteps.steps[stepIndex], ...(step?.nested_breakdown ?? [])]
                        : step?.nested_breakdown
                    )
                        ?.map((b, breakdownIndex) => ({
                            ...b,
                            order: breakdownIndex,
                        }))
                        ?.filter(
                            (b) =>
                                isOnlySeries ||
                                !funnelsFilter?.hidden_legend_breakdowns?.includes(getVisibilityKey(b.breakdown_value))
                        ),
                }))
            },
        ],

        /*
         * Time-to-convert funnels
         */
        timeConversionResults: [
            (s) => [s.results, s.funnelsFilter],
            (results, funnelsFilter): FunnelsTimeConversionBins | null => {
                return funnelsFilter?.funnel_viz_type === FunnelVizType.TimeToConvert
                    ? (results as FunnelsTimeConversionBins)
                    : null
            },
        ],
        histogramGraphData: [
            (s) => [s.timeConversionResults],
            (timeConversionResults: FunnelsTimeConversionBins): HistogramGraphDatum[] | null => {
                if ((timeConversionResults?.bins?.length ?? 0) < 2) {
                    return null // There are no results
                }

                const totalCount = sum(timeConversionResults.bins.map(([, count]) => count))
                if (totalCount === 0) {
                    return [] // Nobody has converted in the time period
                }

                const binSize = timeConversionResults.bins[1][0] - timeConversionResults.bins[0][0]
                return timeConversionResults.bins.map(([id, count]: [id: number, count: number]) => {
                    const value = Math.max(0, id)
                    const percent = totalCount === 0 ? 0 : count / totalCount
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
        hasFunnelResults: [
            (s) => [s.funnelsFilter, s.steps, s.histogramGraphData],
            (funnelsFilter, steps, histogramGraphData) => {
                if (funnelsFilter?.funnel_viz_type === FunnelVizType.Steps || !funnelsFilter?.funnel_viz_type) {
                    return !!(steps && steps[0] && steps[0].count > -1)
                } else if (funnelsFilter.funnel_viz_type === FunnelVizType.TimeToConvert) {
                    return (histogramGraphData?.length ?? 0) > 0
                } else if (funnelsFilter.funnel_viz_type === FunnelVizType.Trends) {
                    return (steps?.length ?? 0) > 0 && !!steps?.[0]?.labels
                } else {
                    return false
                }
            },
        ],
        numericBinCount: [
            (s) => [s.funnelsFilter, s.timeConversionResults],
            (funnelsFilter, timeConversionResults): number => {
                if (funnelsFilter?.bin_count === BIN_COUNT_AUTO) {
                    return timeConversionResults?.bins?.length ?? 0
                }
                return funnelsFilter?.bin_count ?? 0
            },
        ],

        conversionMetrics: [
            (s) => [s.steps, s.funnelsFilter, s.timeConversionResults],
            (steps, funnelsFilter, timeConversionResults): FunnelTimeConversionMetrics => {
                // steps should be empty in time conversion view. Return metrics precalculated on backend
                if (funnelsFilter?.funnel_viz_type === FunnelVizType.TimeToConvert) {
                    return {
                        averageTime: timeConversionResults?.average_conversion_time ?? 0,
                        stepRate: 0,
                        totalRate: 0,
                    }
                }

                // Handle metrics for trends
                if (funnelsFilter?.funnel_viz_type === FunnelVizType.Trends) {
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
                    stepRate: fromStep.count === 0 ? 0 : toStep.count / fromStep.count,
                    totalRate: steps[0].count === 0 ? 0 : steps[steps.length - 1].count / steps[0].count,
                }
            },
        ],
        conversionWindow: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): FunnelConversionWindow => {
                const { funnel_window_interval, funnel_window_interval_unit } = funnelsFilter || {}
                return {
                    funnel_window_interval: funnel_window_interval || 14,
                    funnel_window_interval_unit: funnel_window_interval_unit || FunnelConversionWindowTimeUnit.Day,
                }
            },
        ],
        incompletenessOffsetFromEnd: [
            (s) => [s.steps, s.conversionWindow],
            (steps, conversionWindow) => {
                if (steps?.[0]?.days === undefined) {
                    return 0
                }

                // subtract conversion window from today and look for a matching day
                const startDate = getIncompleteConversionWindowStartDate(conversionWindow)
                const startIndex = steps[0].days.findIndex((day) => dayjs(day) >= startDate)

                if (startIndex !== undefined && startIndex !== -1) {
                    return startIndex - steps[0].days.length
                } else {
                    return 0
                }
            },
        ],

        /*
         * Advanced options: funnel_order_type, funnel_step_reference, exclusions
         */
        advancedOptionsUsedCount: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): number => {
                let count = 0
                if (funnelsFilter?.funnel_order_type && funnelsFilter?.funnel_order_type !== StepOrderValue.ORDERED) {
                    count = count + 1
                }
                if (
                    funnelsFilter?.funnel_step_reference &&
                    funnelsFilter?.funnel_step_reference !== FunnelStepReference.total
                ) {
                    count = count + 1
                }
                if (funnelsFilter?.exclusions?.length) {
                    count = count + 1
                }
                return count
            },
        ],

        // Exclusion filters
        exclusionDefaultStepRange: [
            (s) => [s.querySource],
            (querySource: FunnelsQuery): Omit<FunnelExclusion, 'id' | 'name'> => ({
                funnel_from_step: 0,
                funnel_to_step: (querySource.series || []).length > 1 ? querySource.series.length - 1 : 1,
            }),
        ],
        exclusionFilters: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): FilterType => ({
                events: funnelsFilter?.exclusions,
            }),
        ],
        areExclusionFiltersValid: [
            (s) => [s.insightDataError],
            (insightDataError): boolean => {
                return !(insightDataError?.status === 400 && insightDataError?.type === 'validation_error')
            },
        ],

        isSkewed: [
            (s) => [s.conversionMetrics, s.skewWarningHidden],
            (conversionMetrics, skewWarningHidden): boolean => {
                return !skewWarningHidden && (conversionMetrics.totalRate < 0.1 || conversionMetrics.totalRate > 0.9)
            },
        ],
    })),
])

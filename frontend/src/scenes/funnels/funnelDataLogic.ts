import { kea } from 'kea'
import {
    FilterType,
    FunnelResultType,
    FunnelVizType,
    FunnelStep,
    FunnelStepRangeEntityFilter,
    FunnelStepReference,
    FunnelStepWithNestedBreakdown,
    InsightLogicProps,
    StepOrderValue,
    InsightType,
    FunnelsFilterType,
    FunnelStepWithConversionMetrics,
    FlattenedFunnelStepByBreakdown,
} from '~/types'
import { FunnelsQuery, NodeKind } from '~/queries/schema'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { groupsModel, Noun } from '~/models/groupsModel'

import type { funnelDataLogicType } from './funnelDataLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isFunnelsQuery } from '~/queries/utils'
import {
    aggregateBreakdownResult,
    flattenedStepsByBreakdown,
    getVisibilityKey,
    isBreakdownFunnelResults,
    stepsWithConversionMetrics,
} from './funnelUtils'

const DEFAULT_FUNNEL_LOGIC_KEY = 'default_funnel_key'

export const funnelDataLogic = kea<funnelDataLogicType>({
    path: (key) => ['scenes', 'funnels', 'funnelDataLogic', key],
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_FUNNEL_LOGIC_KEY),

    connect: (props: InsightLogicProps) => ({
        values: [
            insightDataLogic(props),
            ['querySource', 'insightFilter', 'funnelsFilter', 'breakdown'],
            groupsModel,
            ['aggregationLabel'],
            insightLogic(props),
            ['insight', 'hiddenLegendKeys'],
        ],
        actions: [insightDataLogic(props), ['updateInsightFilter', 'updateQuerySource']],
    }),

    selectors: ({ props }) => ({
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
            (
                querySource: FunnelsQuery,
                aggregationLabel: (
                    groupTypeIndex: number | null | undefined,
                    deferToUserWording?: boolean | undefined
                ) => Noun
            ): Noun => aggregationLabel(querySource.aggregation_group_type_index),
        ],

        results: [
            (s) => [s.insight],
            ({
                filters,
                result,
            }: {
                filters: Partial<FunnelsFilterType>
                result: FunnelResultType
            }): FunnelResultType => {
                if (filters?.insight === InsightType.FUNNELS) {
                    if (isBreakdownFunnelResults(result) && result[0][0].breakdowns) {
                        // in order to stop the UI having to check breakdowns and breakdown
                        // this collapses breakdowns onto the breakdown property
                        return result.map((series) =>
                            series.map((step) => {
                                const { breakdowns, ...clone } = step
                                clone.breakdown = breakdowns as (string | number)[]
                                return clone
                            })
                        )
                    }
                    return result
                } else {
                    return []
                }
            },
        ],
        steps: [
            (s) => [s.breakdown, s.results, s.isTimeToConvertFunnel],
            (breakdown, results, isTimeToConvertFunnel): FunnelStepWithNestedBreakdown[] => {
                if (!isTimeToConvertFunnel) {
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
        flattenedBreakdowns: [
            (s) => [s.stepsWithConversionMetrics, s.funnelsFilter],
            (steps, funnelsFilter): FlattenedFunnelStepByBreakdown[] => {
                const disableBaseline = !!props.cachedInsight?.disable_baseline
                return flattenedStepsByBreakdown(steps, funnelsFilter?.layout, disableBaseline, true)
            },
        ],
        visibleStepsWithConversionMetrics: [
            (s) => [s.stepsWithConversionMetrics, s.hiddenLegendKeys, s.flattenedBreakdowns],
            (steps, hiddenLegendKeys, flattenedBreakdowns): FunnelStepWithConversionMetrics[] => {
                const isOnlySeries = flattenedBreakdowns.length <= 1
                const baseLineSteps = flattenedBreakdowns.find((b) => b.isBaseline)
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
            (querySource: FunnelsQuery): Omit<FunnelStepRangeEntityFilter, 'id' | 'name'> => ({
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
    }),
})

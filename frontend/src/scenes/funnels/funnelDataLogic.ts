import { kea } from 'kea'
import {
    FilterType,
    FunnelAPIResponse,
    FunnelVizType,
    FunnelStep,
    FunnelStepRangeEntityFilter,
    FunnelStepReference,
    FunnelStepWithNestedBreakdown,
    InsightLogicProps,
    StepOrderValue,
    InsightType,
} from '~/types'
import { FunnelsQuery } from '~/queries/schema'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { groupsModel, Noun } from '~/models/groupsModel'

import type { funnelDataLogicType } from './funnelDataLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'

const DEFAULT_FUNNEL_LOGIC_KEY = 'default_funnel_key'

export const funnelDataLogic = kea<funnelDataLogicType>({
    path: (key) => ['scenes', 'funnels', 'funnelDataLogic', key],
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_FUNNEL_LOGIC_KEY),

    connect: (props: InsightLogicProps) => ({
        values: [
            insightDataLogic(props),
            ['querySource', 'insightFilter', 'funnelsFilter'],
            groupsModel,
            ['aggregationLabel'],
            insightLogic(props),
            ['insight'],
        ],
        actions: [insightDataLogic(props), ['updateInsightFilter', 'updateQuerySource']],
    }),

    selectors: {
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
            ({ filters, result }): FunnelAPIResponse => {
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
        steps: [
            (s) => [s.funnelsFilter, s.results],
            (funnelsFilter, results: FunnelAPIResponse): FunnelStepWithNestedBreakdown[] => {
                const stepResults =
                    funnelsFilter?.funnel_viz_type !== FunnelVizType.TimeToConvert
                        ? (results as FunnelStep[] | FunnelStep[][])
                        : []

                if (!Array.isArray(stepResults)) {
                    return []
                }

                // TODO: Handle breakdowns
                return ([...stepResults] as FunnelStep[]).sort((a, b) => a.order - b.order)
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
                funnel_to_step: querySource.series.length > 1 ? querySource.series.length - 1 : 1,
            }),
        ],
        exclusionFilters: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): FilterType => ({
                events: funnelsFilter?.exclusions,
            }),
        ],
    },
})

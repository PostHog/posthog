import { kea } from 'kea'
import {
    FilterType,
    FunnelsFilterType,
    FunnelStepRangeEntityFilter,
    FunnelStepReference,
    InsightLogicProps,
    StepOrderValue,
} from '~/types'
import { FunnelsQuery } from '~/queries/schema'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { groupsModel, Noun } from '~/models/groupsModel'

import type { funnelDataLogicType } from './funnelDataLogicType'

const DEFAULT_FUNNEL_LOGIC_KEY = 'default_funnel_key'

export const funnelDataLogic = kea<funnelDataLogicType>({
    path: (key) => ['scenes', 'funnels', 'funnelDataLogic', key],
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_FUNNEL_LOGIC_KEY),

    connect: (props: InsightLogicProps) => ({
        values: [insightDataLogic(props), ['querySource', 'insightFilter'], groupsModel, ['aggregationLabel']],
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
        /*
         * Advanced options: funnel_order_type, funnel_step_reference, exclusions
         */
        advancedOptionsUsedCount: [
            (s) => [s.insightFilter],
            (insightFilter: FunnelsFilterType | undefined): number => {
                let count = 0
                if (insightFilter?.funnel_order_type && insightFilter?.funnel_order_type !== StepOrderValue.ORDERED) {
                    count = count + 1
                }
                if (
                    insightFilter?.funnel_step_reference &&
                    insightFilter?.funnel_step_reference !== FunnelStepReference.total
                ) {
                    count = count + 1
                }
                if (insightFilter?.exclusions?.length) {
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
            (s) => [s.insightFilter],
            (insightFilter: FunnelsFilterType | undefined): FilterType => ({
                events: insightFilter?.exclusions,
            }),
        ],
    },
})

import { kea } from 'kea'
import { FunnelsFilterType, FunnelStepReference, InsightLogicProps, StepOrderValue } from '~/types'
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
        advancedOptionsUsedCount: [
            (s) => [s.insightFilter],
            (insightFilter: FunnelsFilterType): number => {
                let count = 0
                if (insightFilter.funnel_order_type && insightFilter.funnel_order_type !== StepOrderValue.ORDERED) {
                    count = count + 1
                }
                if (
                    insightFilter.funnel_step_reference &&
                    insightFilter.funnel_step_reference !== FunnelStepReference.total
                ) {
                    count = count + 1
                }
                if (insightFilter.exclusions?.length) {
                    count = count + 1
                }
                return count
            },
        ],
    },
})

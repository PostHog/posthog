import { kea } from 'kea'
import { InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

import { groupsModel, Noun } from '~/models/groupsModel'

import type { funnelDataLogicType } from './funnelDataLogicType'
import { FunnelsFilter, FunnelsQuery } from '~/queries/schema'

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
            (querySource: FunnelsQuery, aggregationLabel): Noun =>
                aggregationLabel(querySource.aggregation_group_type_index),
        ],
    },
})

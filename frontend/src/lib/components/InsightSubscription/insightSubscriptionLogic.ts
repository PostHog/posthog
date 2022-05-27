import { kea } from 'kea'
import { InsightModel, SubscriptionType } from '~/types'

import type { insightSubscriptionLogicType } from './insightSubscriptionLogicType'
import api from 'lib/api'

export interface InsightSubscriptionLogicProps {
    insight: Partial<InsightModel>
}
export const insightSubscriptionLogic = kea<insightSubscriptionLogicType>({
    path: ['lib', 'components', 'InsightSubscription', 'insightSubscriptionLogic'],
    props: {} as InsightSubscriptionLogicProps,
    key: ({ insight }) => {
        if (!insight.short_id) {
            throw Error('must provide an insight with a short id')
        }
        return insight.short_id
    },
    actions: {
        addSubscription: true,
    },

    loaders: ({ props }) => ({
        subscriptions: {
            __default: [] as SubscriptionType[],
            loadSubscriptions: async () => {
                if (!props.insight.id) {
                    return []
                }

                const response = await api.subscriptions.list(props.insight.id)
                return response.results
            },
        },
    }),

    events: ({ actions }) => ({
        afterMount: () => actions.loadSubscriptions(),
    }),
})

import { actions, afterMount, kea, key, path, props } from 'kea'
import { InsightModel, SubscriptionType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'

import type { insightSubscriptionsLogicType } from './insightSubscriptionsLogicType'

export interface InsightSubscriptionLogicProps {
    insight: Partial<InsightModel>
}
export const insightSubscriptionsLogic = kea<insightSubscriptionsLogicType>([
    path(['lib', 'components', 'InsightSubscription', 'insightSubscriptionsLogic']),
    props({} as InsightSubscriptionLogicProps),
    key(({ insight }) => {
        if (!insight.short_id) {
            throw Error('must provide an insight with a short id')
        }
        return insight.short_id
    }),
    actions({
        addSubscription: true,
    }),

    loaders(({ props }) => ({
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
    })),

    afterMount(({ actions }) => actions.loadSubscriptions()),
])

import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { InsightShortId, SubscriptionType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'

import type { insightSubscriptionsLogicType } from './insightSubscriptionsLogicType'
import { deleteWithUndo } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'

export interface InsightSubscriptionLogicProps {
    insightShortId: InsightShortId
}
export const insightSubscriptionsLogic = kea<insightSubscriptionsLogicType>([
    path(['lib', 'components', 'InsightSubscription', 'insightSubscriptionsLogic']),
    props({} as InsightSubscriptionLogicProps),
    key(({ insightShortId }) => {
        return insightShortId
    }),
    connect(({ insightShortId }: InsightSubscriptionLogicProps) => ({
        values: [insightLogic({ dashboardItemId: insightShortId }), ['insight']],
    })),
    actions({
        deleteSubscription: (id: number) => ({ id }),
    }),

    loaders(({ values }) => ({
        subscriptions: {
            __default: [] as SubscriptionType[],
            loadSubscriptions: async () => {
                if (!values.insight.id) {
                    return []
                }

                const response = await api.subscriptions.list(values.insight.id)
                return response.results
            },
        },
    })),

    reducers({
        subscriptions: {
            deleteSubscription: (state, { id }) => state.filter((a) => a.id !== id),
        },
    }),

    listeners(({ actions }) => ({
        deleteSubscription: ({ id }) => {
            deleteWithUndo({
                endpoint: api.subscriptions.determineDeleteEndpoint(),
                object: { name: 'Subscription', id },
                callback: () => actions.loadSubscriptions(),
            })
        },
    })),

    afterMount(({ actions }) => actions.loadSubscriptions()),
])

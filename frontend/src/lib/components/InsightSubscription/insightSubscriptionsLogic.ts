import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { InsightModel, SubscriptionType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'

import type { insightSubscriptionsLogicType } from './insightSubscriptionsLogicType'
import { deleteWithUndo } from 'lib/utils'

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
        deleteSubscription: (id: number) => ({ id }),
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

    reducers({
        subscriptions: {
            deleteSubscription: (state, { id }) => {
                return state.filter((a) => a.id !== id)
            },
        },
    }),

    listeners(({ actions }) => ({
        deleteSubscription: async ({ id }) => {
            deleteWithUndo({
                endpoint: api.subscriptions.determineDeleteEndpoint(),
                object: { name: 'Subscription', id },
                callback: () => actions.loadSubscriptions(),
            })
        },
    })),

    afterMount(({ actions }) => actions.loadSubscriptions()),
])

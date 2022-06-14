import { actions, afterMount, BreakPointFunction, kea, key, listeners, path, props, reducers } from 'kea'
import { SubscriptionType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'

import type { insightSubscriptionsLogicType } from './insightSubscriptionsLogicType'
import { deleteWithUndo } from 'lib/utils'

export interface InsightSubscriptionLogicProps {
    insightId?: number
    dashboardId?: number
}
export const insightSubscriptionsLogic = kea<insightSubscriptionsLogicType>([
    path(['lib', 'components', 'InsightSubscription', 'insightSubscriptionsLogic']),
    props({} as InsightSubscriptionLogicProps),
    key(({ insightId, dashboardId }) =>
        insightId ? `insight-${insightId}` : dashboardId ? `dashboard-${dashboardId}` : 'subscriptions'
    ),
    actions({
        deleteSubscription: (id: number) => ({ id }),
    }),

    loaders(({ props }) => ({
        subscriptions: {
            __default: [] as SubscriptionType[],
            loadSubscriptions: async (_?: any, breakpoint?: BreakPointFunction) => {
                if (!props.dashboardId && !props.insightId) {
                    return []
                }

                breakpoint?.()
                console.log(props)
                const response = await api.subscriptions.list({
                    dashboardId: props.dashboardId,
                    insightId: props.insightId,
                })
                breakpoint?.()
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

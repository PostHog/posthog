import { actions, afterMount, BreakPointFunction, kea, key, listeners, path, props, reducers } from 'kea'
import { SubscriptionType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'

import { deleteWithUndo } from 'lib/utils'

import type { subscriptionsLogicType } from './subscriptionsLogicType'
import { getInsightId } from 'scenes/insights/utils'
import { SubscriptionBaseProps } from './utils'

export const subscriptionsLogic = kea<subscriptionsLogicType>([
    path(['lib', 'components', 'Subscriptions', 'subscriptionsLogic']),
    props({} as SubscriptionBaseProps),
    key(({ insightShortId, dashboardId }) =>
        insightShortId ? `insight-${insightShortId}` : dashboardId ? `dashboard-${dashboardId}` : 'subscriptions'
    ),
    actions({
        deleteSubscription: (id: number) => ({ id }),
    }),

    loaders(({ props }) => ({
        subscriptions: {
            __default: [] as SubscriptionType[],
            loadSubscriptions: async (_?: any, breakpoint?: BreakPointFunction) => {
                if (!props.dashboardId && !props.insightShortId) {
                    return []
                }

                breakpoint?.()

                const insightId = props.insightShortId ? await getInsightId(props.insightShortId) : undefined
                const response = await api.subscriptions.list({
                    dashboardId: props.dashboardId,
                    insightId: insightId,
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

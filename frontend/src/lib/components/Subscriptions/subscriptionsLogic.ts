import { BreakPointFunction, actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { getInsightId } from 'scenes/insights/utils'

import { SubscriptionType } from '~/types'

import type { subscriptionsLogicType } from './subscriptionsLogicType'
import { SubscriptionBaseProps } from './utils'

export const subscriptionsLogic = kea<subscriptionsLogicType>([
    path(['lib', 'components', 'Subscriptions', 'subscriptionsLogic']),
    props({} as SubscriptionBaseProps),
    key(({ insightShortId, dashboardId }) =>
        insightShortId ? `insight-${insightShortId}` : dashboardId ? `dashboard-${dashboardId}` : 'subscriptions'
    ),
    actions({
        deleteSubscription: (id: number) => ({ id }),
        deliverSubscription: (id: number) => ({ id }),
        deliverSubscriptionSuccess: true,
        deliverSubscriptionFailure: true,
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
        deliveringSubscriptionId: [
            null as number | null,
            {
                deliverSubscription: (_, { id }) => id,
                deliverSubscriptionSuccess: () => null,
                deliverSubscriptionFailure: () => null,
            },
        ],
    }),

    listeners(({ actions }) => ({
        deleteSubscription: async ({ id }) => {
            await deleteWithUndo({
                endpoint: api.subscriptions.determineDeleteEndpoint(),
                object: { name: 'Subscription', id },
                callback: () => actions.loadSubscriptions(),
            })
        },
        deliverSubscription: async ({ id }) => {
            try {
                await api.subscriptions.testDelivery(id)
                lemonToast.success('Test delivery started')
                actions.deliverSubscriptionSuccess()
            } catch (e: any) {
                if (e.status === 409) {
                    lemonToast.warning('Delivery already in progress')
                } else {
                    lemonToast.error('Failed to deliver subscription')
                }
                actions.deliverSubscriptionFailure()
            }
        },
    })),

    afterMount(({ actions }) => actions.loadSubscriptions()),
])

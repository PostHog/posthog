import { BreakPointFunction, actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { getInsightId } from 'scenes/insights/utils'

import { SubscriptionType } from '~/types'

import { runSubscriptionTestDelivery } from './runSubscriptionTestDelivery'
import type { subscriptionsLogicType } from './subscriptionsLogicType'
import { toggleSubscriptionEnabled } from './toggleSubscriptionEnabled'
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
        setSubscriptionEnabled: (id: number, enabled: boolean) => ({ id, enabled }),
        setSubscriptionEnabledSuccess: true,
        setSubscriptionEnabledFailure: true,
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
        togglingEnabledId: [
            null as number | null,
            {
                setSubscriptionEnabled: (_, { id }) => id,
                setSubscriptionEnabledSuccess: () => null,
                setSubscriptionEnabledFailure: () => null,
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
            const result = await runSubscriptionTestDelivery(() => api.subscriptions.testDelivery(id))
            if (result === 'success') {
                actions.deliverSubscriptionSuccess()
            } else {
                actions.deliverSubscriptionFailure()
            }
        },
        setSubscriptionEnabled: async ({ id, enabled }) => {
            const ok = await toggleSubscriptionEnabled(id, enabled)
            if (ok) {
                actions.setSubscriptionEnabledSuccess()
            } else {
                actions.setSubscriptionEnabledFailure()
            }
        },
        setSubscriptionEnabledSuccess: () => actions.loadSubscriptions(),
    })),

    afterMount(({ actions }) => actions.loadSubscriptions()),
])

import { kea } from 'kea'
import { setPageTitle } from 'lib/utils'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { billingLogic } from './billingLogic'
import { billingSubscribedLogicType } from './billingSubscribedLogicType'

export enum SubscriptionStatus {
    Success = 'success',
    Failed = 'failed',
}

export const billingSubscribedLogic = kea<billingSubscribedLogicType<SubscriptionStatus>>({
    path: ['scenes', 'billing', 'billingSubscribedLogic'],
    connect: {
        actions: [sceneLogic, ['setScene']],
        values: [billingLogic, ['billing']],
    },
    actions: {
        setStatus: (status: SubscriptionStatus) => ({ status }),
        setSessionId: (id: string) => ({ id }),
    },
    reducers: {
        status: [
            SubscriptionStatus.Failed,
            {
                setStatus: (_, { status }) => status,
            },
        ],
        sessionId: [
            null as string | null,
            {
                setSessionId: (_, { id }) => id,
            },
        ],
    },
    listeners: ({ values }) => ({
        setScene: async ({ scene }, breakpoint) => {
            if (scene !== Scene.BillingSubscribed) {
                return
            }
            await breakpoint(100)
            if (values.status === SubscriptionStatus.Success) {
                setPageTitle('Subscribed!')
            } else {
                setPageTitle('Subscription failed')
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/organization/billing/subscribed': (_, { s, session_id }) => {
            if (s === 'success') {
                actions.setStatus(SubscriptionStatus.Success)
            }
            if (session_id) {
                actions.setSessionId(session_id)
            }
        },
    }),
})

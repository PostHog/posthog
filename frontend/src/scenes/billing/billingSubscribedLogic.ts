import { kea } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { billingLogic } from './billingLogic'
import type { billingSubscribedLogicType } from './billingSubscribedLogicType'

export enum SubscriptionStatus {
    Success = 'success',
    Failed = 'failed',
}

export const billingSubscribedLogic = kea<billingSubscribedLogicType>({
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
            SubscriptionStatus.Failed as SubscriptionStatus,
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

import { actions, afterMount, kea, key, path, props } from 'kea'
import { SubscriptionType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'

import type { insightSubscriptionLogicType } from './insightSubscriptionLogicType'

const NEW_SUBSCRIPTION: Partial<SubscriptionType> = {
    schedule: '0 0 0 0 0',
    title: 'New Subscription',
    emails: [],
}

export interface InsightSubscriptionLogicProps {
    id: number | 'new'
    insightId: number
}
export const insightSubscriptionLogic = kea<insightSubscriptionLogicType>([
    path(['lib', 'components', 'InsightSubscription', 'insightSubscriptionLogic']),
    props({} as InsightSubscriptionLogicProps),
    key(({ id, insightId }) => `${insightId}-${id ?? 'new'}`),
    actions({
        createSubscription: (subscription) => ({ subscription }),
    }),

    loaders(({ props }) => ({
        subscription: {
            __default: {} as SubscriptionType,
            loadSubscription: async () => {
                if (props.id && props.id !== 'new') {
                    return await api.subscriptions.get(props.id)
                }
                return { ...NEW_SUBSCRIPTION }
            },
        },
    })),

    forms(({ actions, props }) => ({
        subscription: {
            defaults: { ...NEW_SUBSCRIPTION } as SubscriptionType,
            errors: ({ schedule, title, emails }) => ({
                schedule: !schedule ? 'You need to set a schedule' : undefined,
                title: !title ? 'You need to set a title' : undefined,
                emails:
                    !emails || emails?.length === 0
                        ? ['At least one email is required']
                        : emails.every((email) => email === '1')
                        ? ['All emails must be valid']
                        : undefined,
            }),
            submit: (subscription) => {
                subscription.insight = props.insightId
                actions.createSubscription(subscription)
                console.log('SUBMITTED', subscription)
            },
        },
    })),

    afterMount(({ actions }) => actions.loadSubscription()),
])

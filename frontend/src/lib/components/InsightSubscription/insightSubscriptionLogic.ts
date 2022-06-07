import { actions, afterMount, kea, key, path, props } from 'kea'
import { SubscriptionType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'

import type { insightSubscriptionLogicType } from './insightSubscriptionLogicType'

const NEW_SUBSCRIPTION: Partial<SubscriptionType> = {
    frequency: 'WEEEKLY',
    interval: 1,
    start_date: '2021-01-01T00:00:00', // Make this today
    title: 'New Subscription',
    target_type: 'email',
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
            errors: ({ frequency, interval, title, target_value, target_type }) => ({
                frequency: !frequency ? 'You need to set a schedule frequency' : undefined,
                interval: !interval ? 'You need to set a schedule time' : undefined,
                title: !title ? 'You need to set a title' : undefined,
                target_value:
                    target_type == 'email'
                        ? !target_value
                            ? 'At least one email is required'
                            : target_value.split(',').every((email) => email === '1') // TODO: Email validation
                            ? 'All emails must be valid'
                            : undefined
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

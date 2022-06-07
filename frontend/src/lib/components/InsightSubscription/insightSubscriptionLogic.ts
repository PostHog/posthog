import { actions, afterMount, kea, key, path, props } from 'kea'
import { SubscriptionType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'

import type { insightSubscriptionLogicType } from './insightSubscriptionLogicType'
import { isEmail } from 'lib/utils'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from '../lemonToast'

const NEW_SUBSCRIPTION: Partial<SubscriptionType> = {
    frequency: 'weekly',
    interval: 1,
    start_date: dayjs().hour(9).minute(0).second(0).toISOString(),
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

    forms(({ props }) => ({
        subscription: {
            defaults: { ...NEW_SUBSCRIPTION } as SubscriptionType,
            errors: ({ frequency, interval, target_value, target_type }) => ({
                frequency: !frequency ? 'You need to set a schedule frequency' : undefined,
                interval: !interval ? 'You need to set a schedule time' : undefined,
                target_value:
                    target_type == 'email'
                        ? !target_value
                            ? 'At least one email is required'
                            : !target_value.split(',').every((email) => isEmail(email))
                            ? 'All emails must be valid'
                            : undefined
                        : undefined,
            }),
            submit: async (subscription) => {
                subscription.insight = props.insightId

                if (props.id === 'new') {
                    await api.subscriptions.create(subscription)
                } else {
                    await api.subscriptions.update(props.id, subscription)
                }
                lemonToast.success(`Subscription saved.`)
            },
        },
    })),

    afterMount(({ actions }) => actions.loadSubscription()),
])

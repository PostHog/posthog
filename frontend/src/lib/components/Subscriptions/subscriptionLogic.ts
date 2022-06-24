import { afterMount, connect, kea, key, listeners, path, props } from 'kea'
import { SubscriptionType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'

import { isEmail, isURL } from 'lib/utils'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from '../lemonToast'
import { beforeUnload, router } from 'kea-router'
import { subscriptionsLogic } from './subscriptionsLogic'

import type { subscriptionLogicType } from './subscriptionLogicType'
import { getInsightId } from 'scenes/insights/utils'
import { SubscriptionBaseProps, urlForSubscription } from './utils'

const NEW_SUBSCRIPTION: Partial<SubscriptionType> = {
    frequency: 'weekly',
    interval: 1,
    start_date: dayjs().hour(9).minute(0).second(0).toISOString(),
    target_type: 'email',
    byweekday: ['monday'],
    bysetpos: 1,
}

export interface SubscriptionsLogicProps extends SubscriptionBaseProps {
    id: number | 'new'
}
export const subscriptionLogic = kea<subscriptionLogicType>([
    path(['lib', 'components', 'Subscriptions', 'subscriptionLogic']),
    props({} as SubscriptionsLogicProps),
    key(({ id, insightShortId, dashboardId }) => `${insightShortId || dashboardId}-${id ?? 'new'}`),
    connect(({ insightShortId, dashboardId }: SubscriptionsLogicProps) => ({
        actions: [subscriptionsLogic({ insightShortId, dashboardId }), ['loadSubscriptions']],
    })),

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

    forms(({ props, actions }) => ({
        subscription: {
            defaults: { ...NEW_SUBSCRIPTION } as SubscriptionType,
            errors: ({ frequency, interval, target_value, target_type, title, start_date }) => ({
                frequency: !frequency ? 'You need to set a schedule frequency' : undefined,
                title: !title ? 'You need to give your subscription a name' : undefined,
                interval: !interval ? 'You need to set an interval' : undefined,
                start_date: !start_date ? 'You need to set a delivery time' : undefined,
                target_type: !['slack', 'email', 'webhook'].includes(target_type)
                    ? 'Unsupported target type'
                    : undefined,
                target_value: !target_value
                    ? 'This field is required.'
                    : target_type == 'email'
                    ? !target_value
                        ? 'At least one email is required'
                        : !target_value.split(',').every((email) => isEmail(email))
                        ? 'All emails must be valid'
                        : undefined
                    : target_type == 'slack'
                    ? !target_value
                        ? 'A channel is required'
                        : undefined
                    : target_type == 'webhook'
                    ? !isURL(target_value)
                        ? 'Must be a valid URL'
                        : undefined
                    : undefined,
            }),
            submit: async (subscription, breakpoint) => {
                const insightId = props.insightShortId ? await getInsightId(props.insightShortId) : undefined

                const payload = {
                    ...subscription,
                    insight: insightId,
                    dashboard: props.dashboardId,
                }

                let subscriptionId = props.id

                breakpoint()

                if (subscriptionId === 'new') {
                    const newSub = await api.subscriptions.create(payload)
                    subscriptionId = newSub.id
                } else {
                    await api.subscriptions.update(subscriptionId, payload)
                }

                actions.resetSubscription()

                if (subscriptionId !== props.id) {
                    router.actions.replace(urlForSubscription(subscriptionId, props))
                }

                actions.loadSubscriptions()
                actions.loadSubscription()
                lemonToast.success(`Subscription saved.`)
            },
        },
    })),

    listeners(({ actions }) => ({
        setSubscriptionValue: ({ name, value }) => {
            const key = Array.isArray(name) ? name[0] : name
            if (key === 'frequency') {
                if (value === 'daily') {
                    actions.setSubscriptionValues({
                        bysetpos: null,
                        byweekday: null,
                    })
                } else {
                    actions.setSubscriptionValues({
                        bysetpos: NEW_SUBSCRIPTION.bysetpos,
                        byweekday: NEW_SUBSCRIPTION.byweekday,
                    })
                }
            }

            if (key === 'target_type') {
                actions.setSubscriptionValues({
                    target_value: '',
                })
            }
        },
    })),
    beforeUnload(({ actions, values }) => ({
        enabled: () => values.subscriptionChanged,
        message: 'Changes you made will be discarded.',
        onConfirm: () => {
            actions.resetSubscription()
        },
    })),

    afterMount(({ actions }) => actions.loadSubscription()),
])

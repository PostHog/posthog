import { afterMount, connect, kea, key, listeners, path, props } from 'kea'
import { SubscriptionType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'

import type { insightSubscriptionLogicType } from './insightSubscriptionLogicType'
import { isEmail } from 'lib/utils'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from '../lemonToast'
import { beforeUnload } from 'kea-router'
import { insightSubscriptionsLogic } from './insightSubscriptionsLogic'

const NEW_SUBSCRIPTION: Partial<SubscriptionType> = {
    frequency: 'weekly',
    interval: 1,
    start_date: dayjs().hour(9).minute(0).second(0).toISOString(),
    target_type: 'email',
    byweekday: ['monday'],
    bysetpos: 1,
}

export interface InsightSubscriptionLogicProps {
    id: number | 'new'
    insightId?: number
    dashboardId?: number
}
export const insightSubscriptionLogic = kea<insightSubscriptionLogicType>([
    path(['lib', 'components', 'InsightSubscription', 'insightSubscriptionLogic']),
    props({} as InsightSubscriptionLogicProps),
    key(({ id, insightId, dashboardId }) => `${insightId || dashboardId}-${id ?? 'new'}`),
    connect(({ insightId, dashboardId }: InsightSubscriptionLogicProps) => ({
        actions: [insightSubscriptionsLogic({ insightId, dashboardId }), ['loadSubscriptions']],
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
            errors: ({ frequency, interval, target_value, target_type, title }) => ({
                frequency: !frequency ? 'You need to set a schedule frequency' : undefined,
                title: !title ? 'You need to give your subscription a name' : undefined,
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
            submit: async (subscription, breakpoint) => {
                const payload = {
                    ...subscription,
                    insight: props.insightId,
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

                // TODO: Fix this
                // if (subscriptionId !== props.id) {
                //     router.actions.replace(urls.insightSubcription(props.insightShortId, subscriptionId.toString()))
                // }

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

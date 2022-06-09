import { afterMount, connect, kea, key, path, props } from 'kea'
import { InsightShortId, SubscriptionType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'

import type { insightSubscriptionLogicType } from './insightSubscriptionLogicType'
import { isEmail } from 'lib/utils'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from '../lemonToast'
import { insightLogic } from 'scenes/insights/insightLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { insightSubscriptionsLogic } from './insightSubscriptionsLogic'

const NEW_SUBSCRIPTION: Partial<SubscriptionType> = {
    frequency: 'weekly',
    interval: 1,
    start_date: dayjs().hour(9).minute(0).second(0).toISOString(),
    target_type: 'email',
}

export interface InsightSubscriptionLogicProps {
    id: number | 'new'
    insightShortId: InsightShortId
}
export const insightSubscriptionLogic = kea<insightSubscriptionLogicType>([
    path(['lib', 'components', 'InsightSubscription', 'insightSubscriptionLogic']),
    props({} as InsightSubscriptionLogicProps),
    key(({ id, insightShortId }) => `${insightShortId}-${id ?? 'new'}`),
    connect(({ insightShortId }: InsightSubscriptionLogicProps) => ({
        values: [insightLogic({ dashboardItemId: insightShortId }), ['insight']],
        actions: [insightSubscriptionsLogic({ insightShortId }), ['loadSubscriptions']],
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

    forms(({ props, values, actions }) => ({
        subscription: {
            defaults: { ...NEW_SUBSCRIPTION } as SubscriptionType,
            errors: ({ frequency, interval, target_value, target_type, title }) => ({
                frequency: !frequency ? 'You need to set a schedule frequency' : undefined,
                title: !title ? 'You need to give your subscripiton a name' : undefined,
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
                subscription.insight = values.insight.id

                let subscriptionId = props.id

                if (props.id === 'new') {
                    const newSub = await api.subscriptions.create(subscription)
                    subscriptionId = newSub.id
                } else {
                    await api.subscriptions.update(props.id, subscription)
                }
                actions.loadSubscriptions()
                actions.loadSubscription()
                actions.resetSubscription()
                lemonToast.success(`Subscription saved.`)

                if (subscriptionId !== props.id) {
                    await breakpoint(150) // Allow enough time for the unload hook to be removed
                    router.actions.replace(urls.insightSubcription(props.insightShortId, subscriptionId.toString()))
                }
            },
        },
    })),

    afterMount(({ actions }) => actions.loadSubscription()),
])

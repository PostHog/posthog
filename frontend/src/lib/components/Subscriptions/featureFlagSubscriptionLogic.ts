import { connect, events, kea, key, path, props, selectors } from 'kea'
import { SubscriptionType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'

import { dayjs } from 'lib/dayjs'
import { userLogic } from 'scenes/userLogic'

export const NEW_FEATURE_FLAG_SUBSCRIPTION: Partial<SubscriptionType> = {
    frequency: 'on_change',
    interval: 0,
    start_date: dayjs().toISOString(),
    target_type: 'in_app_notification',
    target_value: '',
}

export interface FeatureFlagSubscriptionsLogicProps {
    featureFlagId?: number
}

export const featureFlagSubscriptionLogic = kea([
    path(['lib', 'components', 'Subscriptions', 'subscriptionLogic']),
    props({} as FeatureFlagSubscriptionsLogicProps),
    key(({ id, featureFlagId }) => `${featureFlagId}-${id ?? 'new'}`),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    loaders(({ props, values }) => ({
        subscription: {
            __default: null as SubscriptionType | null,
            loadSubscription: async () => {
                if (props.featureFlagId) {
                    const candidateMatches = await api.subscriptions.list({
                        featureFlagId: props.featureFlagId,
                        createdById: values.user.uuid,
                    })
                    return candidateMatches.results[0] || null
                }
                return null
            },
            createSubscription: async () => {
                return await api.subscriptions.create({
                    ...NEW_FEATURE_FLAG_SUBSCRIPTION,
                    feature_flag: props.featureFlagId,
                })
            },
            deleteSubscription: async () => {
                return await api.subscriptions.update(values.subscription.id, { deleted: true })
            },
        },
    })),
    selectors({ isSubscribed: [(s) => [s.subscription], (subscription) => !!subscription && !subscription.deleted] }),
    events(({ actions }) => ({
        afterMount() {
            actions.loadSubscription()
        },
    })),
])

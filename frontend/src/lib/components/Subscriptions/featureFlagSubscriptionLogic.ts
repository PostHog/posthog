import { connect, events, kea, key, path, props, selectors } from 'kea'
import { AvailableFeature, SubscriptionType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'

import { dayjs } from 'lib/dayjs'
import { userLogic } from 'scenes/userLogic'

import type { featureFlagSubscriptionLogicType } from './featureFlagSubscriptionLogicType'
import { lemonToast } from 'lib/components/lemonToast'

export const NEW_FEATURE_FLAG_SUBSCRIPTION: Partial<SubscriptionType> = {
    frequency: 'on_change',
    interval: 0,
    start_date: dayjs().toISOString(),
    target_type: 'in_app_notification',
    target_value: '',
}

export interface FeatureFlagSubscriptionsLogicProps {
    featureFlagId?: string | number
}

export const featureFlagSubscriptionLogic = kea<featureFlagSubscriptionLogicType>([
    path(['lib', 'components', 'Subscriptions', 'subscriptionLogic']),
    props({} as FeatureFlagSubscriptionsLogicProps),
    key(({ featureFlagId }) => `feature-flag-subscription-${featureFlagId}`),
    connect(() => ({
        values: [userLogic, ['user', 'hasAvailableFeature']],
    })),
    loaders(({ props, values }) => ({
        subscription: {
            __default: null as SubscriptionType | null,
            loadSubscription: async () => {
                const featureFlagId: number = Number(props.featureFlagId)

                if (featureFlagId && !isNaN(featureFlagId) && values.user) {
                    const candidateMatches = await api.subscriptions.list({
                        featureFlagId: featureFlagId,
                        createdById: values.user.uuid,
                    })
                    return candidateMatches.results[0] || null
                }
                return null
            },
            createSubscription: async () => {
                const createResponse = (await api.subscriptions.create({
                    ...NEW_FEATURE_FLAG_SUBSCRIPTION,
                    feature_flag: Number(props.featureFlagId),
                })) as SubscriptionType
                lemonToast.success('In-App Notification Subscription created!')
                return createResponse
            },
            deleteSubscription: async () => {
                if (values.subscription?.id !== undefined) {
                    const deleteResponse = (await api.subscriptions.update(values.subscription.id, {
                        deleted: true,
                    })) as SubscriptionType
                    lemonToast.success('In-App Notification Subscription removed!')
                    return deleteResponse
                }
            },
        },
    })),
    selectors({ isSubscribed: [(s) => [s.subscription], (subscription) => !!subscription && !subscription.deleted] }),
    events(({ actions, values }) => ({
        afterMount() {
            if (values.hasAvailableFeature(AvailableFeature.SUBSCRIPTIONS)) {
                actions.loadSubscription()
            }
        },
    })),
])

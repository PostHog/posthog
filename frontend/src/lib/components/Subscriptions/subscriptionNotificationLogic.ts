import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { projectLogic } from 'scenes/projectLogic'

import { HogFunctionType, IntegrationType } from '~/types'

import type { subscriptionNotificationLogicType } from './subscriptionNotificationLogicType'
import {
    PendingSubscriptionNotification,
    SUBSCRIPTION_DELIVERED_EVENT_ID,
    SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD,
    SUBSCRIPTION_NOTIFICATION_TYPE_SLACK,
    SUBSCRIPTION_NOTIFICATION_TYPE_WEBHOOK,
    SubscriptionNotificationType,
    buildSubscriptionHogFunctionPayload,
    firesForSubscription,
    isPinnedToSubscription,
} from './subscriptionNotificationUtils'

export const SUBSCRIPTION_NOTIFICATION_TYPE_OPTIONS = [
    { label: 'Slack', value: SUBSCRIPTION_NOTIFICATION_TYPE_SLACK },
    { label: 'Discord', value: SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD },
    { label: 'Webhook', value: SUBSCRIPTION_NOTIFICATION_TYPE_WEBHOOK },
]

export interface SubscriptionNotificationLogicProps {
    subscriptionId?: number
}

export const subscriptionNotificationLogic = kea<subscriptionNotificationLogicType>([
    path(['lib', 'components', 'Subscriptions', 'subscriptionNotificationLogic']),
    props({} as SubscriptionNotificationLogicProps),
    key(({ subscriptionId }) => subscriptionId ?? 'new'),

    connect({
        values: [projectLogic, ['currentProjectId'], integrationsLogic, ['slackIntegrations']],
        actions: [integrationsLogic, ['loadIntegrationsSuccess']],
    }),

    actions({
        addPendingNotification: (notification: PendingSubscriptionNotification) => ({ notification }),
        removePendingNotification: (index: number) => ({ index }),
        clearPendingNotifications: true,
        setPendingNotifications: (notifications: PendingSubscriptionNotification[]) => ({ notifications }),
        deleteExistingHogFunction: (hogFunction: HogFunctionType) => ({ hogFunction }),
        createPendingHogFunctions: (subscriptionId: number, subscriptionName?: string) => ({
            subscriptionId,
            subscriptionName,
        }),
        setSelectedType: (selectedType: SubscriptionNotificationType) => ({ selectedType }),
        setSlackChannelValue: (slackChannelValue: string | null) => ({ slackChannelValue }),
        setWebhookUrl: (webhookUrl: string) => ({ webhookUrl }),
    }),

    reducers({
        pendingNotifications: [
            [] as PendingSubscriptionNotification[],
            {
                addPendingNotification: (state, { notification }) => [...state, notification],
                removePendingNotification: (state, { index }) => state.filter((_, i) => i !== index),
                clearPendingNotifications: () => [],
                setPendingNotifications: (_, { notifications }) => notifications,
            },
        ],
        slackChannelValue: [
            null as string | null,
            {
                setSlackChannelValue: (_, { slackChannelValue }) => slackChannelValue,
            },
        ],
        webhookUrl: [
            '' as string,
            {
                setWebhookUrl: (_, { webhookUrl }) => webhookUrl,
            },
        ],
        selectedType: [
            SUBSCRIPTION_NOTIFICATION_TYPE_SLACK as SubscriptionNotificationType,
            {
                setSelectedType: (_, { selectedType }) => selectedType,
            },
        ],
        existingHogFunctions: [
            [] as HogFunctionType[],
            {
                // Optimistic removal so the item disappears immediately
                deleteExistingHogFunction: (state, { hogFunction }) => state.filter((hf) => hf.id !== hogFunction.id),
            },
        ],
    }),

    selectors({
        firstSlackIntegration: [
            (s) => [s.slackIntegrations],
            (slackIntegrations: IntegrationType[] | undefined): IntegrationType | undefined => slackIntegrations?.[0],
        ],
    }),

    loaders(({ props }) => ({
        existingHogFunctions: [
            [] as HogFunctionType[],
            {
                loadExistingHogFunctions: async () => {
                    if (props.subscriptionId == null) {
                        return []
                    }
                    // Query the event only (no subscription_id pin), then keep destinations that
                    // fire for this report — team-wide (unpinned) plus ones pinned to this sub.
                    const response = await api.hogFunctions.list({
                        types: ['internal_destination'],
                        filter_groups: [{ events: [{ id: SUBSCRIPTION_DELIVERED_EVENT_ID, type: 'events' }] }],
                        full: true,
                    })
                    return response.results.filter((hf) => firesForSubscription(hf, props.subscriptionId as number))
                },
            },
        ],
    })),

    listeners(({ actions, values, props }) => ({
        loadIntegrationsSuccess: () => {
            if (!values.firstSlackIntegration) {
                actions.setSelectedType(SUBSCRIPTION_NOTIFICATION_TYPE_WEBHOOK)
            }
        },
        deleteExistingHogFunction: async ({ hogFunction }) => {
            // Guard: only this-sub destinations are deletable here; team-wide ones are managed in the library.
            if (props.subscriptionId == null || !isPinnedToSubscription(hogFunction, props.subscriptionId)) {
                return
            }
            await deleteWithUndo({
                endpoint: `projects/${values.currentProjectId}/hog_functions`,
                object: { id: hogFunction.id, name: hogFunction.name },
                callback: (undo) => {
                    if (undo) {
                        actions.loadExistingHogFunctions()
                    }
                },
            })
        },

        createPendingHogFunctions: async ({ subscriptionId, subscriptionName }) => {
            const pending = values.pendingNotifications
            if (pending.length === 0) {
                return
            }

            const results = await Promise.allSettled(
                pending.map((notification) =>
                    api.hogFunctions.create(
                        buildSubscriptionHogFunctionPayload(subscriptionId, subscriptionName, notification)
                    )
                )
            )

            const failedNotifications = pending.filter((_, i) => results[i].status === 'rejected')

            if (failedNotifications.length > 0) {
                lemonToast.error(
                    `Subscription saved, but ${failedNotifications.length} automation(s) failed to create. Reopen the subscription to add them again.`
                )
                actions.setPendingNotifications(failedNotifications)
            } else {
                if (results.length > 0) {
                    lemonToast.success(`${results.length} automation(s) connected.`)
                }
                actions.clearPendingNotifications()
            }

            actions.loadExistingHogFunctions()
        },
    })),

    afterMount(({ actions, props }) => {
        if (props.subscriptionId != null) {
            actions.loadExistingHogFunctions()
        }
    }),
])

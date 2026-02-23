import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import {
    ALERT_NOTIFICATION_TYPE_SLACK,
    ALERT_NOTIFICATION_TYPE_WEBHOOK,
    AlertNotificationType,
    PendingAlertNotification,
    buildAlertFilterConfig,
    buildHogFunctionPayload,
} from 'lib/utils/alertUtils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { projectLogic } from 'scenes/projectLogic'

import { HogFunctionType, IntegrationType } from '~/types'

import type { alertNotificationLogicType } from './alertNotificationLogicType'

export const ALERT_NOTIFICATION_TYPE_OPTIONS = [
    { label: 'Slack', value: ALERT_NOTIFICATION_TYPE_SLACK },
    { label: 'Webhook', value: ALERT_NOTIFICATION_TYPE_WEBHOOK },
]

export interface AlertNotificationLogicProps {
    alertId?: string
}

export const alertNotificationLogic = kea<alertNotificationLogicType>([
    path(['lib', 'components', 'Alerts', 'alertNotificationLogic']),
    props({} as AlertNotificationLogicProps),
    key(({ alertId }) => alertId ?? 'new'),

    connect({
        values: [projectLogic, ['currentProjectId'], integrationsLogic, ['slackIntegrations']],
        actions: [integrationsLogic, ['loadIntegrationsSuccess']],
    }),

    actions({
        addPendingNotification: (notification: PendingAlertNotification) => ({ notification }),
        removePendingNotification: (index: number) => ({ index }),
        clearPendingNotifications: true,
        setPendingNotifications: (notifications: PendingAlertNotification[]) => ({ notifications }),
        deleteExistingHogFunction: (hogFunction: HogFunctionType) => ({ hogFunction }),
        createPendingHogFunctions: (alertId: string, alertName?: string) => ({ alertId, alertName }),
        setSelectedType: (selectedType: AlertNotificationType) => ({ selectedType }),
        setSlackChannelValue: (slackChannelValue: string | null) => ({ slackChannelValue }),
        setWebhookUrl: (webhookUrl: string) => ({ webhookUrl }),
    }),

    reducers({
        pendingNotifications: [
            [] as PendingAlertNotification[],
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
            ALERT_NOTIFICATION_TYPE_SLACK as AlertNotificationType,
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
        // Use first available Slack integration to determine if Slack should be the default notification type
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
                    if (!props.alertId) {
                        return []
                    }
                    const response = await api.hogFunctions.list({
                        types: ['internal_destination'],
                        filter_groups: [buildAlertFilterConfig(props.alertId)],
                        full: true,
                    })
                    return response.results
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        loadIntegrationsSuccess: () => {
            if (!values.firstSlackIntegration) {
                actions.setSelectedType(ALERT_NOTIFICATION_TYPE_WEBHOOK)
            }
        },
        deleteExistingHogFunction: async ({ hogFunction }) => {
            await deleteWithUndo({
                endpoint: `projects/${values.currentProjectId}/hog_functions`,
                object: {
                    id: hogFunction.id,
                    name: hogFunction.name,
                },
                callback: (undo) => {
                    if (undo) {
                        actions.loadExistingHogFunctions()
                    }
                },
            })
        },

        createPendingHogFunctions: async ({ alertId, alertName }) => {
            const pending = values.pendingNotifications
            if (pending.length === 0) {
                return
            }

            const results = await Promise.allSettled(
                pending.map((notification) => {
                    const payload = buildHogFunctionPayload(alertId, alertName, notification)
                    return api.hogFunctions.create(payload)
                })
            )

            const failedNotifications = pending.filter((_, i) => results[i].status === 'rejected')

            if (failedNotifications.length > 0) {
                lemonToast.error(
                    `Alert saved, but ${failedNotifications.length} notification(s) failed to create. Reopen the alert to add them again.`
                )
                actions.setPendingNotifications(failedNotifications)
            } else {
                if (results.length > 0) {
                    lemonToast.success(`${results.length} notification destination(s) created.`)
                }
                actions.clearPendingNotifications()
            }

            actions.loadExistingHogFunctions()
        },
    })),

    afterMount(({ actions, props }) => {
        if (props.alertId) {
            actions.loadExistingHogFunctions()
        }
    }),
])

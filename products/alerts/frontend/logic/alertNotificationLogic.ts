import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { projectLogic } from 'scenes/projectLogic'

import { HogFunctionType, IntegrationType } from '~/types'

import {
    ALERT_NOTIFICATION_TYPE_DISCORD,
    ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS,
    ALERT_NOTIFICATION_TYPE_SLACK,
    ALERT_NOTIFICATION_TYPE_WEBHOOK,
    AlertNotificationType,
    PendingAlertNotification,
    buildAlertFilterConfig,
    buildHogFunctionPayload,
} from 'products/alerts/frontend/logic/alertNotifications'

import type { alertNotificationLogicType } from './alertNotificationLogicType'

export const ALERT_NOTIFICATION_TYPE_OPTIONS = [
    { label: 'Slack', value: ALERT_NOTIFICATION_TYPE_SLACK },
    { label: 'Discord', value: ALERT_NOTIFICATION_TYPE_DISCORD },
    { label: 'Microsoft Teams', value: ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS },
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
                // Reset the input when switching destination type so stale values don't carry over.
                setSelectedType: () => null,
            },
        ],
        webhookUrl: [
            '' as string,
            {
                setWebhookUrl: (_, { webhookUrl }) => webhookUrl,
                setSelectedType: () => '',
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

            const failures = results
                .map((result, i) => ({ result, notification: pending[i] }))
                .filter(
                    (item): item is { result: PromiseRejectedResult; notification: PendingAlertNotification } =>
                        item.result.status === 'rejected'
                )

            if (failures.length > 0) {
                const labelForType = (type: AlertNotificationType): string =>
                    ALERT_NOTIFICATION_TYPE_OPTIONS.find((option) => option.value === type)?.label ?? type
                // Log each failure with its destination type + API error so the cause is diagnosable later.
                failures.forEach(({ result, notification }) => {
                    console.error(
                        `Failed to create ${labelForType(notification.type)} alert notification`,
                        result.reason
                    )
                })
                const failedTypes = Array.from(
                    new Set(failures.map(({ notification }) => labelForType(notification.type)))
                )
                lemonToast.error(
                    `Alert saved, but failed to create: ${failedTypes.join(', ')}. Reopen the alert to add them again.`
                )
                actions.setPendingNotifications(failures.map(({ notification }) => notification))
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

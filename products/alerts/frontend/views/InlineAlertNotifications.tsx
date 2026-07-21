import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { slackIntegrationLogic } from 'lib/integrations/slackIntegrationLogic'
import { urls } from 'scenes/urls'

import { HogFunctionType, SlackChannelType } from '~/types'

import {
    AlertNotificationDestinationEditor,
    AlertNotificationDestinationView,
    AlertNotificationUrlInput,
    PendingAlertNotificationDestinationView,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'
import {
    ALERT_NOTIFICATION_TYPE_DISCORD,
    ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS,
    ALERT_NOTIFICATION_TYPE_SLACK,
    ALERT_NOTIFICATION_TYPE_WEBHOOK,
    AlertNotificationType,
    PendingAlertNotification,
} from 'products/alerts/frontend/logic/alertNotifications'

import { ALERT_NOTIFICATION_TYPE_OPTIONS, alertNotificationLogic } from '../logic/alertNotificationLogic'

function resolveSlackChannelName(channelValue: string, slackChannels: SlackChannelType[]): string | null {
    const channelId = channelValue.split('|')[0]
    return slackChannels.find((channel) => channel.id === channelId)?.name ?? null
}

function getHogFunctionDestination(
    hogFunction: HogFunctionType,
    slackChannels: SlackChannelType[]
): { type: string; detail: string | null } {
    const channelValue = hogFunction.inputs?.channel?.value
    if (channelValue && typeof channelValue === 'string') {
        const channelName = resolveSlackChannelName(channelValue, slackChannels)
        return { type: 'Slack', detail: channelName ? `#${channelName}` : null }
    }
    if (channelValue) {
        return { type: 'Slack', detail: null }
    }
    if (hogFunction.template_id === 'template-discord') {
        const webhookUrl = hogFunction.inputs?.webhookUrl?.value
        return { type: 'Discord', detail: typeof webhookUrl === 'string' ? webhookUrl : null }
    }
    if (hogFunction.template_id === 'template-microsoft-teams') {
        const webhookUrl = hogFunction.inputs?.webhookUrl?.value
        return { type: 'Microsoft Teams', detail: typeof webhookUrl === 'string' ? webhookUrl : null }
    }
    const urlValue = hogFunction.inputs?.url?.value
    if (urlValue && typeof urlValue === 'string') {
        return { type: 'Webhook', detail: urlValue }
    }
    return { type: hogFunction.name, detail: null }
}

function getNotificationLabel(notification: PendingAlertNotification): string {
    switch (notification.type) {
        case ALERT_NOTIFICATION_TYPE_SLACK:
            return `Slack: #${notification.slackChannelName ?? 'channel'}`
        case ALERT_NOTIFICATION_TYPE_DISCORD:
            return `Discord: ${notification.webhookUrl}`
        case ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS:
            return `Microsoft Teams: ${notification.webhookUrl}`
        case ALERT_NOTIFICATION_TYPE_WEBHOOK:
            return `Webhook: ${notification.webhookUrl}`
        default: {
            const exhaustiveCheck: never = notification
            return exhaustiveCheck
        }
    }
}

function getUrlInput(type: AlertNotificationType): AlertNotificationUrlInput | undefined {
    switch (type) {
        case ALERT_NOTIFICATION_TYPE_DISCORD:
            return { placeholder: 'https://discord.com/api/webhooks/...' }
        case ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS:
            return { placeholder: 'https://<region>.logic.azure.com:443/workflows/...' }
        case ALERT_NOTIFICATION_TYPE_WEBHOOK:
            return { placeholder: 'https://example.com/webhook' }
        case ALERT_NOTIFICATION_TYPE_SLACK:
            return undefined
        default: {
            const exhaustiveCheck: never = type
            return exhaustiveCheck
        }
    }
}

function getAddDisabledReason(
    selectedType: AlertNotificationType,
    hasSlackIntegration: boolean,
    slackChannelValue: string | null,
    webhookUrl: string
): string | undefined {
    if (selectedType === ALERT_NOTIFICATION_TYPE_SLACK) {
        if (!hasSlackIntegration) {
            return 'Connect Slack first'
        }
        if (!slackChannelValue) {
            return 'Select a Slack channel'
        }
        return undefined
    }
    if (webhookUrl) {
        return undefined
    }
    if (selectedType === ALERT_NOTIFICATION_TYPE_DISCORD) {
        return 'Enter a Discord webhook URL'
    }
    if (selectedType === ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS) {
        return 'Enter a Microsoft Teams workflow URL'
    }
    return 'Enter a webhook URL'
}

interface InlineAlertNotificationsProps {
    alertId?: string
}

export function InlineAlertNotifications({ alertId }: InlineAlertNotificationsProps): JSX.Element {
    const logic = alertNotificationLogic({ alertId })
    const {
        existingHogFunctions,
        existingHogFunctionsLoading,
        pendingNotifications,
        firstSlackIntegration,
        selectedType,
        slackChannelValue,
        webhookUrl,
    } = useValues(logic)
    const {
        addPendingNotification,
        removePendingNotification,
        deleteExistingHogFunction,
        setSelectedType,
        setSlackChannelValue,
        setWebhookUrl,
    } = useActions(logic)

    const slackLogic = slackIntegrationLogic({ id: firstSlackIntegration?.id ?? 0 })
    const { slackChannels } = useValues(slackLogic)
    const { loadAllSlackChannels } = useActions(slackLogic)

    useEffect(() => {
        if (firstSlackIntegration) {
            loadAllSlackChannels()
        }
    }, [firstSlackIntegration?.id, loadAllSlackChannels, firstSlackIntegration])

    const buildPendingNotification = (): PendingAlertNotification | null => {
        if (selectedType === ALERT_NOTIFICATION_TYPE_SLACK) {
            if (!slackChannelValue || !firstSlackIntegration) {
                return null
            }
            const [channelId, channelLabel] = slackChannelValue.split('|')
            return {
                type: ALERT_NOTIFICATION_TYPE_SLACK,
                slackWorkspaceId: firstSlackIntegration.id,
                slackChannelId: channelId,
                slackChannelName: channelLabel?.replace('#', '') ?? channelId,
            }
        }
        if (!webhookUrl) {
            return null
        }
        if (selectedType === ALERT_NOTIFICATION_TYPE_DISCORD) {
            return { type: ALERT_NOTIFICATION_TYPE_DISCORD, webhookUrl }
        }
        if (selectedType === ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS) {
            return { type: ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS, webhookUrl }
        }
        return { type: ALERT_NOTIFICATION_TYPE_WEBHOOK, webhookUrl }
    }

    const handleAdd = (): void => {
        const notification = buildPendingNotification()
        if (!notification) {
            return
        }
        addPendingNotification(notification)
        if (notification.type === ALERT_NOTIFICATION_TYPE_SLACK) {
            setSlackChannelValue(null)
            return
        }
        setWebhookUrl('')
    }

    const existingDestinations: AlertNotificationDestinationView[] = existingHogFunctions.map((hogFunction) => {
        const destination = getHogFunctionDestination(hogFunction, slackChannels)
        return {
            key: hogFunction.id,
            title: destination.type,
            detail: destination.detail,
            tags: [
                { label: hogFunction.enabled ? 'Active' : 'Paused', type: hogFunction.enabled ? 'success' : 'default' },
            ],
            viewAction: {
                kind: 'icon',
                url: urls.hogFunction(hogFunction.id),
                tooltip: 'Open destination',
                targetBlank: true,
            },
            onDelete: () => deleteExistingHogFunction(hogFunction),
        }
    })

    const pendingDestinations: PendingAlertNotificationDestinationView[] = pendingNotifications.map(
        (notification, index) => ({
            key: `${notification.type}-${index}`,
            label: getNotificationLabel(notification),
            status: '(pending, click Save to apply)',
            onRemove: () => removePendingNotification(index),
        })
    )

    const urlInput = getUrlInput(selectedType)

    return (
        <AlertNotificationDestinationEditor
            destinations={{
                showExisting: Boolean(alertId),
                existingLoading: existingHogFunctionsLoading,
                existing: existingDestinations,
                pending: pendingDestinations,
            }}
            notificationType={{
                options: ALERT_NOTIFICATION_TYPE_OPTIONS,
                value: selectedType,
                onChange: setSelectedType,
            }}
            slack={{
                notificationType: ALERT_NOTIFICATION_TYPE_SLACK,
                integration: firstSlackIntegration,
                channelValue: slackChannelValue,
                onChannelValueChange: setSlackChannelValue,
            }}
            url={urlInput ? { input: urlInput, value: webhookUrl, onChange: setWebhookUrl } : undefined}
            add={{
                onClick: handleAdd,
                disabledReason: getAddDisabledReason(
                    selectedType,
                    Boolean(firstSlackIntegration),
                    slackChannelValue,
                    webhookUrl
                ),
            }}
        />
    )
}

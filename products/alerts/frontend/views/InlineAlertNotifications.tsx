import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { slackIntegrationLogic } from 'lib/integrations/slackIntegrationLogic'
import { urls } from 'scenes/urls'

import { HogFunctionType, IntegrationType, SlackChannelType } from '~/types'

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

// Existing destinations can belong to any connected workspace, not just the one currently
// selected in the picker, so each row resolves its own channel name from its own workspace.
function SlackDestinationChannel({
    workspaceId,
    channelValue,
}: {
    workspaceId: number
    channelValue: string
}): JSX.Element {
    const { slackChannels } = useValues(slackIntegrationLogic({ id: workspaceId }))
    const channelName = resolveSlackChannelName(channelValue, slackChannels)
    return <>{channelName ? `#${channelName}` : 'channel'}</>
}

// Written by every producer of this destination (inline alerts, error tracking alerts, logs
// alerting, MCP) as `{value: int}` / `{value: str}`. Destinations from before `slack_workspace`
// existed simply lack the key — that's the only real-world gap, not a type mismatch.
interface SlackDestinationInputs {
    slack_workspace?: { value: number }
    channel?: { value: string }
}

function getHogFunctionDestination(
    hogFunction: HogFunctionType,
    slackIntegrations: IntegrationType[] | undefined
): { type: string; detail: ReactNode } {
    const inputs = hogFunction.inputs as SlackDestinationInputs | null | undefined
    const channelValue = inputs?.channel?.value
    if (channelValue) {
        const workspaceId = inputs?.slack_workspace?.value
        const workspaceName = slackIntegrations?.find((integration) => integration.id === workspaceId)?.display_name
        if (workspaceId === undefined) {
            return { type: 'Slack', detail: workspaceName ?? null }
        }
        return {
            type: 'Slack',
            detail: (
                <>
                    {workspaceName ?? 'Unknown workspace'} ·{' '}
                    <SlackDestinationChannel workspaceId={workspaceId} channelValue={channelValue} />
                </>
            ),
        }
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

function getNotificationLabel(
    notification: PendingAlertNotification,
    slackIntegrations: IntegrationType[] | undefined
): string {
    switch (notification.type) {
        case ALERT_NOTIFICATION_TYPE_SLACK: {
            const workspaceName = slackIntegrations?.find(
                (integration) => integration.id === notification.slackWorkspaceId
            )?.display_name
            return `Slack: ${workspaceName ?? 'Unknown workspace'} · #${notification.slackChannelName ?? 'channel'}`
        }
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
        slackIntegrations,
        selectedSlackIntegration,
        selectedType,
        slackChannelValue,
        webhookUrl,
    } = useValues(logic)
    const {
        addPendingNotification,
        removePendingNotification,
        deleteExistingHogFunction,
        setSelectedType,
        setSelectedSlackIntegrationId,
        setSlackChannelValue,
        setWebhookUrl,
    } = useActions(logic)

    const buildPendingNotification = (): PendingAlertNotification | null => {
        if (selectedType === ALERT_NOTIFICATION_TYPE_SLACK) {
            if (!slackChannelValue || !selectedSlackIntegration) {
                return null
            }
            const [channelId, channelLabel] = slackChannelValue.split('|')
            return {
                type: ALERT_NOTIFICATION_TYPE_SLACK,
                slackWorkspaceId: selectedSlackIntegration.id,
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
        const destination = getHogFunctionDestination(hogFunction, slackIntegrations)
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
            label: getNotificationLabel(notification, slackIntegrations),
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
                integrations: slackIntegrations,
                integration: selectedSlackIntegration,
                onIntegrationChange: setSelectedSlackIntegrationId,
                channelValue: slackChannelValue,
                onChannelValueChange: setSlackChannelValue,
            }}
            url={urlInput ? { input: urlInput, value: webhookUrl, onChange: setWebhookUrl } : undefined}
            add={{
                onClick: handleAdd,
                disabledReason: getAddDisabledReason(
                    selectedType,
                    Boolean(selectedSlackIntegration),
                    slackChannelValue,
                    webhookUrl
                ),
            }}
        />
    )
}

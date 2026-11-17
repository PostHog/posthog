import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useState } from 'react'

import api from 'lib/api'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { IntegrationType } from '~/types'

import {
    AlertNotificationDestinationEditor,
    AlertNotificationDestinationView,
    AlertNotificationUrlInput,
    PendingAlertNotificationDestinationView,
    pagerDutyPendingDetail,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'
import { destinationMessageAction } from 'products/alerts/frontend/components/destinationMessageAction'
import type { AlertDestinationListItemApi } from 'products/alerts/frontend/generated/api.schemas'
import {
    ALERT_NOTIFICATION_TYPE_DISCORD,
    ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS,
    ALERT_NOTIFICATION_TYPE_PAGERDUTY,
    ALERT_NOTIFICATION_TYPE_SLACK,
    ALERT_NOTIFICATION_TYPE_WEBHOOK,
    AlertNotificationType,
    PendingAlertNotification,
    getAlertNotificationAddDisabledReason,
} from 'products/alerts/frontend/logic/alertNotifications'

import {
    ALERT_NOTIFICATION_TYPE_OPTIONS,
    alertNotificationLogic,
    destinationKey,
} from '../logic/alertNotificationLogic'

// Fetched directly rather than through slackIntegrationLogic's loader: that loader keeps a
// single last-result slot per workspace, so multiple destination rows in the same workspace
// looking up different channels concurrently would cancel each other's requests.
function SlackDestinationChannel({ workspaceId, channelId }: { workspaceId: number; channelId: string }): JSX.Element {
    const [channelName, setChannelName] = useState<string | null>(null)

    useEffect(() => {
        let cancelled = false
        api.integrations.slackChannelsById(workspaceId, channelId).then((res) => {
            if (!cancelled) {
                setChannelName(res.channels[0]?.name ?? null)
            }
        })
        return () => {
            cancelled = true
        }
    }, [workspaceId, channelId])

    return <>{channelName ? `#${channelName}` : 'channel'}</>
}

const DESTINATION_TYPE_LABELS: Record<AlertDestinationListItemApi['type'], string> = {
    slack: 'Slack',
    discord: 'Discord',
    teams: 'Microsoft Teams',
    webhook: 'Webhook',
    pagerduty: 'PagerDuty',
    email: 'Email',
    in_app: 'In-app',
}

function getDestinationDetail(
    destination: AlertDestinationListItemApi,
    slackIntegrations: IntegrationType[] | undefined
): ReactNode {
    if (destination.type === 'slack' && destination.slack_channel_id) {
        // Destinations from before `slack_workspace` existed can only be safely attributed to a
        // workspace when exactly one is connected — with 2+, there's no way to know which one it
        // was created against, so guessing would risk showing the wrong workspace/channel.
        const workspaceId =
            destination.slack_workspace_id ?? (slackIntegrations?.length === 1 ? slackIntegrations[0].id : undefined)
        if (workspaceId === undefined) {
            return null
        }
        const workspaceName = slackIntegrations?.find((integration) => integration.id === workspaceId)?.display_name
        return (
            <>
                {workspaceName ?? 'Unknown workspace'} ·{' '}
                {destination.slack_channel_name ? (
                    `#${destination.slack_channel_name}`
                ) : (
                    <SlackDestinationChannel workspaceId={workspaceId} channelId={destination.slack_channel_id} />
                )}
            </>
        )
    }
    if (destination.type === 'pagerduty') {
        // The API returns only the routing key's last four characters.
        return [destination.pagerduty_routing_key, destination.pagerduty_severity].filter(Boolean).join(' · ')
    }
    return destination.webhook_url ?? null
}

function getPendingNotificationDestination(
    notification: PendingAlertNotification,
    slackIntegrations: IntegrationType[] | undefined
): Pick<PendingAlertNotificationDestinationView, 'title' | 'detail'> {
    switch (notification.type) {
        case ALERT_NOTIFICATION_TYPE_SLACK: {
            const workspaceName = slackIntegrations?.find(
                (integration) => integration.id === notification.slackWorkspaceId
            )?.display_name
            return {
                title: 'Slack',
                detail: `${workspaceName ?? 'Unknown workspace'} · #${notification.slackChannelName ?? 'channel'}`,
            }
        }
        case ALERT_NOTIFICATION_TYPE_DISCORD:
            return { title: 'Discord', detail: notification.webhookUrl }
        case ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS:
            return { title: 'Microsoft Teams', detail: notification.webhookUrl }
        case ALERT_NOTIFICATION_TYPE_WEBHOOK:
            return { title: 'Webhook', detail: notification.webhookUrl }
        case ALERT_NOTIFICATION_TYPE_PAGERDUTY:
            return { title: 'PagerDuty', detail: pagerDutyPendingDetail(notification) }
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
        case ALERT_NOTIFICATION_TYPE_PAGERDUTY:
            return undefined
        default: {
            const exhaustiveCheck: never = type
            return exhaustiveCheck
        }
    }
}

interface InlineAlertNotificationsProps {
    alertId?: string
    /** Whether the alerts platform owns the alert, or will own it once it is created. Only it opens incidents. */
    pagerDutyAvailable: boolean
}

export function InlineAlertNotifications({ alertId, pagerDutyAvailable }: InlineAlertNotificationsProps): JSX.Element {
    const logic = alertNotificationLogic({ alertId })
    const {
        destinations,
        destinationsLoading,
        changingMessageDestinationKeys,
        pendingNotifications,
        integrationsLoading,
        integrationsFailed,
        slackIntegrations,
        selectedSlackIntegration,
        selectedType: storedSelectedType,
        slackChannelValue,
        webhookUrl,
        pagerDutyRoutingKey,
        pagerDutySeverity,
        pagerDutyRegion,
    } = useValues(logic)
    const {
        addPendingNotification,
        removePendingNotification,
        deleteDestination,
        customizeDestination,
        resetDestinationMessage,
        setSelectedType,
        setSelectedSlackIntegrationId,
        setSlackChannelValue,
        setWebhookUrl,
        setPagerDutyRoutingKey,
        setPagerDutySeverity,
        setPagerDutyRegion,
        loadIntegrations,
    } = useActions(logic)

    const messageCustomization = useFeatureFlag('ALERTS_DESTINATION_CUSTOMIZATION')
    // PagerDuty's insight messages cannot be edited, and only an alert PostHog alerts checks sends the standard message.
    const offersMessageAction = (destination: AlertDestinationListItemApi): boolean =>
        messageCustomization &&
        (destination.message_customized ? pagerDutyAvailable : destination.type !== ALERT_NOTIFICATION_TYPE_PAGERDUTY)

    const selectedType =
        !pagerDutyAvailable && storedSelectedType === ALERT_NOTIFICATION_TYPE_PAGERDUTY
            ? ALERT_NOTIFICATION_TYPE_SLACK
            : storedSelectedType

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
        if (selectedType === ALERT_NOTIFICATION_TYPE_PAGERDUTY) {
            return {
                type: ALERT_NOTIFICATION_TYPE_PAGERDUTY,
                routingKey: pagerDutyRoutingKey.trim(),
                severity: pagerDutySeverity,
                region: pagerDutyRegion,
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
        if (notification.type === ALERT_NOTIFICATION_TYPE_PAGERDUTY) {
            setPagerDutyRoutingKey('')
            return
        }
        setWebhookUrl('')
    }

    const existingDestinations: AlertNotificationDestinationView[] = destinations.map((destination) => {
        const hogFunctionId = destination.hog_function_ids[0]
        return {
            key: destinationKey(destination),
            title: DESTINATION_TYPE_LABELS[destination.type] ?? destination.type,
            detail: getDestinationDetail(destination, slackIntegrations),
            tags: [
                destination.type === ALERT_NOTIFICATION_TYPE_PAGERDUTY && !pagerDutyAvailable
                    ? { label: 'Not paging', type: 'warning' }
                    : {
                          label: destination.enabled ? 'Active' : 'Paused',
                          type: destination.enabled ? 'success' : 'default',
                      },
            ],
            viewAction:
                hogFunctionId && destination.type !== ALERT_NOTIFICATION_TYPE_PAGERDUTY
                    ? {
                          kind: 'icon',
                          url: urls.hogFunction(hogFunctionId),
                          tooltip: 'Open destination',
                          targetBlank: true,
                      }
                    : undefined,
            messageAction: offersMessageAction(destination)
                ? destinationMessageAction({
                      messageCustomized: destination.message_customized,
                      loading: changingMessageDestinationKeys.has(destinationKey(destination)),
                      onCustomize: () => customizeDestination(destination),
                      onReset: () => resetDestinationMessage(destination),
                  })
                : undefined,
            onDelete: () => deleteDestination(destination),
        }
    })

    const pendingDestinations: PendingAlertNotificationDestinationView[] = pendingNotifications.map(
        (notification, index) => ({
            key: `${notification.type}-${index}`,
            ...getPendingNotificationDestination(notification, slackIntegrations),
            onRemove: () => removePendingNotification(index),
        })
    )

    const urlInput = getUrlInput(selectedType)

    return (
        <div>
            <AlertNotificationDestinationEditor
                destinations={{
                    showExisting: Boolean(alertId),
                    existingLoading: destinationsLoading,
                    existing: existingDestinations,
                    pending: pendingDestinations,
                }}
                notificationType={{
                    options: ALERT_NOTIFICATION_TYPE_OPTIONS.filter(
                        (option) => pagerDutyAvailable || option.value !== ALERT_NOTIFICATION_TYPE_PAGERDUTY
                    ),
                    value: selectedType,
                    onChange: setSelectedType,
                }}
                slack={{
                    notificationType: ALERT_NOTIFICATION_TYPE_SLACK,
                    integrationsLoading,
                    integrationsFailed,
                    onRetryIntegrations: loadIntegrations,
                    integrations: slackIntegrations,
                    integration: selectedSlackIntegration,
                    onIntegrationChange: setSelectedSlackIntegrationId,
                    channelValue: slackChannelValue,
                    onChannelValueChange: setSlackChannelValue,
                }}
                url={urlInput ? { input: urlInput, value: webhookUrl, onChange: setWebhookUrl } : undefined}
                pagerduty={
                    selectedType === ALERT_NOTIFICATION_TYPE_PAGERDUTY
                        ? {
                              routingKey: pagerDutyRoutingKey,
                              onRoutingKeyChange: setPagerDutyRoutingKey,
                              severity: pagerDutySeverity,
                              onSeverityChange: setPagerDutySeverity,
                              region: pagerDutyRegion,
                              onRegionChange: setPagerDutyRegion,
                          }
                        : undefined
                }
                add={{
                    onClick: handleAdd,
                    disabledReason: getAlertNotificationAddDisabledReason(
                        selectedType,
                        Boolean(selectedSlackIntegration),
                        slackChannelValue,
                        webhookUrl,
                        pagerDutyRoutingKey
                    ),
                }}
            />
        </div>
    )
}

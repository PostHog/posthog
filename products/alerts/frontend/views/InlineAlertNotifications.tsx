import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useState } from 'react'

import api from 'lib/api'
import { INSIGHT_ALERT_FIRING_EVENT_ID } from 'lib/constants'
import { urls } from 'scenes/urls'

import { HogFunctionType, IntegrationType } from '~/types'

import {
    AlertNotificationDestinationEditor,
    AlertNotificationDestinationView,
    AlertNotificationUrlInput,
    PendingAlertNotificationDestinationView,
    pagerDutyDestinationLabel,
    pagerDutyPendingDetail,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'
import {
    ALERT_NOTIFICATION_TYPE_DISCORD,
    ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS,
    ALERT_NOTIFICATION_TYPE_PAGERDUTY,
    ALERT_NOTIFICATION_TYPE_SLACK,
    ALERT_NOTIFICATION_TYPE_WEBHOOK,
    AlertNotificationType,
    PendingAlertNotification,
    getAlertNotificationAddDisabledReason,
    listensOnEvent,
} from 'products/alerts/frontend/logic/alertNotifications'

import { ALERT_NOTIFICATION_TYPE_OPTIONS, alertNotificationLogic } from '../logic/alertNotificationLogic'

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

interface SlackDestinationInputs {
    slack_workspace?: { value: number }
    channel?: { value: string }
}

function getHogFunctionDestination(
    hogFunction: HogFunctionType,
    slackIntegrations: IntegrationType[] | undefined
): { type: string; detail: ReactNode } {
    const inputs = hogFunction.inputs as SlackDestinationInputs | null | undefined
    const channelId = inputs?.channel?.value
    if (channelId) {
        // Destinations from before `slack_workspace` existed can only be safely attributed to a
        // workspace when exactly one is connected — with 2+, there's no way to know which one it
        // was created against, so guessing would risk showing the wrong workspace/channel.
        const workspaceId =
            inputs?.slack_workspace?.value ?? (slackIntegrations?.length === 1 ? slackIntegrations[0].id : undefined)
        if (workspaceId === undefined) {
            return { type: 'Slack', detail: null }
        }
        const workspaceName = slackIntegrations?.find((integration) => integration.id === workspaceId)?.display_name
        return {
            type: 'Slack',
            detail: (
                <>
                    {workspaceName ?? 'Unknown workspace'} ·{' '}
                    <SlackDestinationChannel workspaceId={workspaceId} channelId={channelId} />
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
        existingHogFunctions,
        existingHogFunctionsLoading,
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
        deleteExistingHogFunction,
        deleteExistingPagerDutyDestination,
        setSelectedType,
        setSelectedSlackIntegrationId,
        setSlackChannelValue,
        setWebhookUrl,
        setPagerDutyRoutingKey,
        setPagerDutySeverity,
        setPagerDutyRegion,
        loadIntegrations,
    } = useActions(logic)

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

    // One PagerDuty destination is a trigger function and a resolve function, shown and removed as one.
    // The key holds what the backend groups on, apart from the secret routing key, whose tail is in the name.
    const pagerDutyGroups = new Map<string, { label: string; incident: boolean; hogFunctions: HogFunctionType[] }>()
    for (const hogFunction of existingHogFunctions) {
        if (hogFunction.template_id === 'template-pagerduty') {
            const label = pagerDutyDestinationLabel(hogFunction) ?? hogFunction.id
            const incident = !listensOnEvent(hogFunction, INSIGHT_ALERT_FIRING_EVENT_ID)
            const key = [label, incident, hogFunction.inputs?.severity?.value, hogFunction.inputs?.region?.value].join(
                '|'
            )
            const group = pagerDutyGroups.get(key) ?? { label, incident, hogFunctions: [] }
            group.hogFunctions.push(hogFunction)
            pagerDutyGroups.set(key, group)
        }
    }
    const pagerDutyDestinations: AlertNotificationDestinationView[] = Array.from(pagerDutyGroups.entries()).map(
        ([key, { label, incident, hogFunctions }]) => {
            const enabled = hogFunctions.every((hogFunction) => hogFunction.enabled)
            return {
                key: `pagerduty:${key}`,
                title: 'PagerDuty',
                detail: label.replace(/^PagerDuty\s*/, ''),
                // A legacy PagerDuty destination on the firing event pages from either stack.
                tags: [
                    incident && !pagerDutyAvailable
                        ? { label: 'Not paging', type: 'warning' }
                        : { label: enabled ? 'Active' : 'Paused', type: enabled ? 'success' : 'default' },
                ],
                onDelete: () => deleteExistingPagerDutyDestination(hogFunctions),
            }
        }
    )

    const otherDestinations: AlertNotificationDestinationView[] = existingHogFunctions
        .filter((hogFunction) => hogFunction.template_id !== 'template-pagerduty')
        .map((hogFunction) => {
            const destination = getHogFunctionDestination(hogFunction, slackIntegrations)
            return {
                key: hogFunction.id,
                title: destination.type,
                detail: destination.detail,
                tags: [
                    {
                        label: hogFunction.enabled ? 'Active' : 'Paused',
                        type: hogFunction.enabled ? 'success' : 'default',
                    },
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
    const existingDestinations = [...otherDestinations, ...pagerDutyDestinations]

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
                    existingLoading: existingHogFunctionsLoading,
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

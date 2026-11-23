import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconLetter } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import {
    AlertNotificationDestinationEditor,
    AlertNotificationDestinationView,
    AlertNotificationUrlInput,
    PendingAlertNotificationDestinationView,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'
import { WarehouseAlertDestinationTypeEnumApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { NOTIFICATION_TYPE_OPTIONS, describeNotification } from './warehouseAlertNotificationFormat'
import { destinationKey, warehouseAlertNotificationLogic } from './warehouseAlertNotificationLogic'

const URL_INPUTS: Partial<Record<WarehouseAlertDestinationTypeEnumApi, AlertNotificationUrlInput>> = {
    [WarehouseAlertDestinationTypeEnumApi.Webhook]: { placeholder: 'https://example.com/webhook' },
    [WarehouseAlertDestinationTypeEnumApi.Teams]: {
        placeholder: 'https://prod-00.westus.logic.azure.com:443/workflows/...',
        helpText: 'Paste the URL from a Teams "Workflows" (Power Automate) or incoming webhook connector.',
    },
    [WarehouseAlertDestinationTypeEnumApi.Discord]: {
        placeholder: 'https://discord.com/api/webhooks/...',
        helpText: 'Paste the webhook URL from the Discord channel settings, under Integrations.',
    },
}

function notificationTitle(type: WarehouseAlertDestinationTypeEnumApi, title: string): ReactNode {
    if (type !== WarehouseAlertDestinationTypeEnumApi.Email) {
        return title
    }
    return (
        <span className="inline-flex items-center gap-1">
            <IconLetter className="shrink-0" />
            {title}
        </span>
    )
}

export function WarehouseAlertNotifications({ alertId }: { alertId?: string }): JSX.Element {
    const logic = warehouseAlertNotificationLogic({ alertId })
    const {
        destinations,
        destinationsLoading,
        destinationsFailed,
        deletingKey,
        pendingNotifications,
        integrationsLoading,
        integrationsFailed,
        slackIntegrations,
        selectedSlackIntegration,
        selectedType,
        slackChannelValue,
        webhookUrl,
        pagerDutyRoutingKey,
        pagerDutySeverity,
        pagerDutyRegion,
        emailUserIds,
        memberNames,
        addDisabledReason,
    } = useValues(logic)
    const {
        addSelectedNotification,
        removePendingNotification,
        deleteDestination,
        loadDestinations,
        loadIntegrations,
        setSelectedType,
        setSelectedSlackIntegrationId,
        setSlackChannelValue,
        setWebhookUrl,
        setPagerDutyRoutingKey,
        setPagerDutySeverity,
        setPagerDutyRegion,
        setEmailUserIds,
    } = useActions(logic)

    const existing: AlertNotificationDestinationView[] = (destinations ?? []).map((destination) => {
        const { title, detail } = describeNotification(destination, memberNames)
        return {
            key: destinationKey(destination),
            title: notificationTitle(destination.type, title),
            detail,
            tags: destination.enabled ? [] : [{ label: 'Paused', type: 'default' as const }],
            onDelete: () => deleteDestination(destination),
            deleting: deletingKey === destinationKey(destination),
        }
    })

    const pending: PendingAlertNotificationDestinationView[] = pendingNotifications.map((notification, index) => {
        const { title, detail } = describeNotification(notification, memberNames)
        return {
            key: `${notification.type}-${index}`,
            title: notificationTitle(notification.type, title),
            detail,
            onRemove: () => removePendingNotification(index),
        }
    })

    const urlInput = URL_INPUTS[selectedType]

    return (
        <div className="flex flex-col gap-2">
            {destinationsFailed ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry',
                        onClick: () => loadDestinations(),
                        'data-attr': 'warehouse-alert-notifications-retry',
                    }}
                >
                    Couldn't load this alert's notification destinations.
                </LemonBanner>
            ) : null}
            <AlertNotificationDestinationEditor
                description="Each destination gets a message when the alert fires and when it resolves. PagerDuty opens an incident when the alert fires and resolves it when the alert resolves. Email skips members who can't view warehouse sources or who turned off data pipeline error emails."
                destinations={{
                    showExisting: !!alertId,
                    existingLoading: destinationsLoading && destinations === null,
                    existing,
                    pending,
                    pendingTooltip: 'Added when you create the alert',
                }}
                notificationType={{
                    options: NOTIFICATION_TYPE_OPTIONS,
                    value: selectedType,
                    onChange: setSelectedType,
                    dropdownPlacement: 'top-start',
                }}
                slack={{
                    notificationType: WarehouseAlertDestinationTypeEnumApi.Slack,
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
                    selectedType === WarehouseAlertDestinationTypeEnumApi.Pagerduty
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
                members={
                    selectedType === WarehouseAlertDestinationTypeEnumApi.Email
                        ? { value: emailUserIds, onChange: setEmailUserIds }
                        : undefined
                }
                add={{ onClick: addSelectedNotification, disabledReason: addDisabledReason }}
            />
        </div>
    )
}

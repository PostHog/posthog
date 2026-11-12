import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import {
    AlertNotificationDestinationEditor,
    AlertNotificationDestinationView,
    PendingAlertNotificationDestinationView,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'
import { PlatformAlertDestinationTypeEnumApi } from 'products/alerts_platform/frontend/generated/api.schemas'

import { DESTINATION_TYPE_OPTIONS, describeDestination, describePendingDestination } from './platformAlertDestinations'
import { PlatformAlertDestinationsLogicProps, platformAlertDestinationsLogic } from './platformAlertDestinationsLogic'

/** An alert's own notification destinations, in the editor every alert product uses. */
export function PlatformAlertNotifications({ alertId, sourceKind }: PlatformAlertDestinationsLogicProps): JSX.Element {
    const logic = platformAlertDestinationsLogic({ alertId, sourceKind })
    const {
        destinations,
        destinationsLoading,
        destinationsLoadFailed,
        deletingDestinationIds,
        pendingDestinations,
        integrationsLoading,
        integrationsFailed,
        slackIntegrations,
        slackIntegration,
        selectedType,
        slackChannelValue,
        webhookUrl,
        urlInput,
        pagerDutyRoutingKey,
        pagerDutySeverity,
        pagerDutyRegion,
        addDisabledReason,
    } = useValues(logic)
    const {
        addSelectedDestination,
        removePendingDestination,
        deleteDestination,
        setSelectedType,
        setSlackChannelValue,
        setWebhookUrl,
        setPagerDutyRoutingKey,
        setPagerDutySeverity,
        setPagerDutyRegion,
        loadIntegrations,
        loadDestinations,
        setSelectedSlackIntegrationId,
    } = useActions(logic)

    const existing: AlertNotificationDestinationView[] = destinations.map((destination) => ({
        key: destination.id,
        ...describeDestination(destination),
        tags: destination.enabled ? undefined : [{ label: 'Paused' }],
        onDelete: () => deleteDestination(destination),
        deleting: deletingDestinationIds.has(destination.id),
    }))

    const pending: PendingAlertNotificationDestinationView[] = pendingDestinations.map((destination, index) => ({
        key: `${destination.type}-${index}`,
        ...describePendingDestination(destination),
        onRemove: () => removePendingDestination(index),
    }))

    return (
        <div className="space-y-2">
            {destinationsLoadFailed ? (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadDestinations() }}>
                    Could not load this alert's destinations. Retry before you add or remove any.
                </LemonBanner>
            ) : null}
            <AlertNotificationDestinationEditor
                description="Each destination gets a notification when the alert fires, resolves, errors, or breaks. PagerDuty gets an incident that opens when the alert fires and resolves when it resolves."
                destinations={{
                    showExisting: !!alertId,
                    existingLoading: destinationsLoading,
                    existing,
                    pending,
                    pendingTooltip: alertId
                        ? 'Could not be added. Remove it and add it again.'
                        : 'Added when you create the alert',
                }}
                notificationType={{
                    options: DESTINATION_TYPE_OPTIONS,
                    value: selectedType,
                    onChange: setSelectedType,
                }}
                slack={{
                    notificationType: PlatformAlertDestinationTypeEnumApi.Slack,
                    integrationsLoading,
                    integrationsFailed,
                    onRetryIntegrations: loadIntegrations,
                    integrations: slackIntegrations,
                    integration: slackIntegration,
                    onIntegrationChange: setSelectedSlackIntegrationId,
                    channelValue: slackChannelValue,
                    onChannelValueChange: setSlackChannelValue,
                }}
                url={urlInput ? { input: urlInput, value: webhookUrl, onChange: setWebhookUrl } : undefined}
                pagerduty={
                    selectedType === PlatformAlertDestinationTypeEnumApi.Pagerduty
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
                add={{ onClick: addSelectedDestination, disabledReason: addDisabledReason }}
            />
        </div>
    )
}

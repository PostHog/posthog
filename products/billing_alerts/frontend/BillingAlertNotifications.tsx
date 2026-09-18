import { useActions, useValues } from 'kea'

import {
    AlertNotificationDestinationEditor,
    AlertNotificationDestinationView,
    PendingAlertNotificationDestinationView,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'

import { destinationLabel } from './billingAlertDisplay'
import {
    BillingAlertNotificationLogicProps,
    BillingAlertNotificationType,
    billingAlertNotificationLogic,
} from './billingAlertNotificationLogic'
import { destinationKey } from './billingAlertUtils'

const DESTINATION_OPTIONS = [
    { value: 'slack' as const, label: 'Slack' },
    { value: 'teams' as const, label: 'Microsoft Teams' },
    { value: 'webhook' as const, label: 'Webhook' },
]

export function BillingAlertNotifications(props: BillingAlertNotificationLogicProps): JSX.Element {
    const logic = billingAlertNotificationLogic(props)
    const {
        pendingDestinations,
        selectedType,
        integrationsLoading,
        integrationsFailed,
        slackIntegrations,
        selectedSlackIntegration,
        slackChannel,
        webhookUrl,
        addDisabledReason,
        deletingDestinationKeys,
    } = useValues(logic)
    const {
        setSelectedType,
        setSelectedIntegrationId,
        setSlackChannel,
        setWebhookUrl,
        addSelectedDestination,
        removePendingDestination,
        deleteDestination,
        loadIntegrations,
    } = useActions(logic)

    const existingDestinations: AlertNotificationDestinationView[] = (props.alert?.destinations ?? []).map(
        (destination) => ({
            key: destinationKey(destination),
            title: destinationLabel(destination.type),
            detail: 'Firing, resolved, errored, and auto-disabled notifications',
            tags: [{ label: 'Active', type: 'success' }],
            onDelete: () => deleteDestination(destination),
            deleting: deletingDestinationKeys.has(destinationKey(destination)),
        })
    )
    const pendingViews: PendingAlertNotificationDestinationView[] = pendingDestinations.map((destination) => ({
        key: destination.key,
        title: destination.label,
        detail: 'Save the alert to apply this notification',
        onRemove: () => removePendingDestination(destination.key),
    }))

    return (
        <div data-attr="billing-alert-notifications">
            <AlertNotificationDestinationEditor<BillingAlertNotificationType>
                description="Each destination receives firing, resolved, errored, and auto-disabled notifications."
                destinations={{
                    showExisting: true,
                    existingLoading: false,
                    existing: existingDestinations,
                    pending: pendingViews,
                }}
                notificationType={{
                    options: DESTINATION_OPTIONS,
                    value: selectedType,
                    onChange: setSelectedType,
                    dropdownPlacement: 'top-start',
                }}
                slack={{
                    notificationType: 'slack',
                    integrationsLoading,
                    integrationsFailed,
                    onRetryIntegrations: loadIntegrations,
                    integrations: slackIntegrations,
                    integration: selectedSlackIntegration,
                    onIntegrationChange: setSelectedIntegrationId,
                    channelValue: slackChannel,
                    onChannelValueChange: setSlackChannel,
                }}
                url={
                    selectedType === 'slack'
                        ? undefined
                        : {
                              input: {
                                  placeholder:
                                      selectedType === 'teams'
                                          ? 'https://<region>.logic.azure.com/...'
                                          : 'https://example.com/webhook',
                              },
                              value: webhookUrl,
                              onChange: setWebhookUrl,
                          }
                }
                add={{ onClick: addSelectedDestination, disabledReason: addDisabledReason }}
            />
        </div>
    )
}

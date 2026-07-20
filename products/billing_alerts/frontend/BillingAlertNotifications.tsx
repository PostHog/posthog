import { useActions, useValues } from 'kea'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { urls } from 'scenes/urls'

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
        selectedIntegrationId,
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
    } = useActions(logic)

    const existingDestinations: AlertNotificationDestinationView[] = (props.alert?.destinations ?? []).map(
        (destination) => ({
            key: `${destination.type}-${destination.hog_function_ids.join('-')}`,
            title: destinationLabel(destination.type),
            detail: 'Firing, resolved, errored, and auto-disabled notifications',
            tags: [{ label: 'Active', type: 'success' }],
            viewAction: destination.hog_function_ids[0]
                ? {
                      kind: 'icon',
                      url: urls.hogFunction(destination.hog_function_ids[0]),
                      tooltip: 'Open destination',
                      targetBlank: true,
                  }
                : undefined,
            onDelete: () => deleteDestination(destination),
            deleting: deletingDestinationKeys.has(`${destination.type}-${destination.hog_function_ids.join('-')}`),
        })
    )
    const pendingViews: PendingAlertNotificationDestinationView[] = pendingDestinations.map((destination) => ({
        key: destination.key,
        label: destination.label,
        status: '(pending, save alert to apply)',
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
                }}
                slack={{
                    notificationType: 'slack',
                    integration: selectedSlackIntegration,
                    workspaceSelector: selectedSlackIntegration ? (
                        <IntegrationChoice
                            integration="slack"
                            value={selectedIntegrationId ?? undefined}
                            onChange={setSelectedIntegrationId}
                        />
                    ) : undefined,
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

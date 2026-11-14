import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonDialog } from '@posthog/lemon-ui'

import { slackIntegrationLogic } from 'lib/integrations/slackIntegrationLogic'

import {
    AlertNotificationDestinationEditor,
    AlertNotificationDestinationMessageAction,
    AlertNotificationDestinationView,
    PendingAlertNotificationDestinationView,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'
import { PlatformAlertDestinationTypeEnumApi } from 'products/alerts_platform/frontend/generated/api.schemas'

import {
    AlertDestinationEntry,
    DESTINATION_TYPE_OPTIONS,
    describeDestination,
    describePendingDestination,
} from './platformAlertDestinations'
import { PlatformAlertDestinationsLogicProps, platformAlertDestinationsLogic } from './platformAlertDestinationsLogic'

export interface PlatformAlertNotificationsProps extends PlatformAlertDestinationsLogicProps {
    /** The destination types the product sends to, when it does not send to every type. */
    typeOptions?: typeof DESTINATION_TYPE_OPTIONS
    /** What the product adds to a saved destination's row, such as a link to edit its message. */
    destinationView?: (destination: AlertDestinationEntry) => Partial<AlertNotificationDestinationView>
    /** Offer "Customize" and "Reset to standard message" on each saved destination. Needs `api.customize` and `api.reset`. */
    messageCustomization?: boolean
}

/** An alert's own notification destinations, in the editor every alert product uses. */
export function PlatformAlertNotifications({
    alertId,
    sourceKind,
    api,
    typeOptions = DESTINATION_TYPE_OPTIONS,
    destinationView,
    messageCustomization = false,
}: PlatformAlertNotificationsProps): JSX.Element {
    const logic = platformAlertDestinationsLogic({ alertId, sourceKind, api })
    const {
        destinations,
        destinationsLoading,
        destinationsLoadFailed,
        deletingDestinationIds,
        changingMessageDestinationIds,
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
        customizeDestination,
        resetDestinationMessage,
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

    // A Slack destination saved before its channel's name was kept shows the name Slack has for it now.
    const unnamedSlackWorkspaceId = destinations.find(
        (destination) =>
            destination.type === PlatformAlertDestinationTypeEnumApi.Slack && !destination.slack_channel_name
    )?.slack_workspace_id
    const slackLogic = slackIntegrationLogic({ id: unnamedSlackWorkspaceId ?? 0 })
    const { slackChannels } = useValues(slackLogic)
    const { loadAllSlackChannels } = useActions(slackLogic)
    useEffect(() => {
        if (unnamedSlackWorkspaceId) {
            loadAllSlackChannels()
        }
    }, [unnamedSlackWorkspaceId, loadAllSlackChannels])

    const messageAction = (destination: AlertDestinationEntry): AlertNotificationDestinationMessageAction =>
        destination.message_customized
            ? {
                  label: 'Reset to standard message',
                  tooltip: 'Send the standard PostHog message instead of your edited one',
                  onClick: () =>
                      LemonDialog.open({
                          title: 'Reset to the standard message?',
                          description:
                              "This destination will send PostHog's standard message. Your edits to its message are deleted.",
                          primaryButton: {
                              children: 'Reset',
                              status: 'danger',
                              onClick: () => resetDestinationMessage(destination),
                              'data-attr': 'alert-destination-reset-message-confirm',
                          },
                          secondaryButton: { children: 'Cancel' },
                      }),
                  loading: changingMessageDestinationIds.has(destination.id),
                  dataAttr: 'alert-destination-reset-message',
              }
            : {
                  label: 'Customize',
                  tooltip: 'Edit the message this destination sends',
                  onClick: () => customizeDestination(destination),
                  loading: changingMessageDestinationIds.has(destination.id),
                  dataAttr: 'alert-destination-customize-message',
              }

    const existing: AlertNotificationDestinationView[] = destinations.map((destination) => ({
        key: destination.id,
        ...describeDestination({
            ...destination,
            slack_channel_name:
                destination.slack_channel_name ??
                slackChannels.find((channel) => channel.id === destination.slack_channel_id)?.name,
        }),
        tags: destination.enabled ? undefined : [{ label: 'Paused' }],
        onDelete: () => deleteDestination(destination),
        deleting: deletingDestinationIds.has(destination.id),
        messageAction: messageCustomization ? messageAction(destination) : undefined,
        ...destinationView?.(destination),
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
                    options: typeOptions,
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

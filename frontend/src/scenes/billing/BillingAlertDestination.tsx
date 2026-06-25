import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { IntegrationType } from '~/types'

import {
    BILLING_ALERT_DESTINATIONS,
    destinationDisabledReason,
    destinationLabel,
    destinationWebhookLabel,
} from './billingAlertDisplay'
import { billingAlertsLogic } from './billingAlertsLogic'
import type { BillingAlertDestinationKey } from './billingAlertsLogic'

const BILLING_ALERT_DESTINATION_SELECT_OPTIONS = BILLING_ALERT_DESTINATIONS.map((destination) => ({
    value: destination.key,
    label: destination.name,
    icon: <img src={destination.icon} alt="" className="h-5 w-5 object-contain" />,
}))

export function BillingAlertDestinationFields(): JSX.Element {
    const { selectedDestinationKey, slackIntegrationId, slackChannel, webhookUrl } = useValues(billingAlertsLogic)
    const { setSelectedDestinationKey, setSlackIntegrationId, setSlackChannel, setWebhookUrl } =
        useActions(billingAlertsLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)

    const slackIntegrations = integrations?.filter((integration) => integration.kind === 'slack') ?? []
    const selectedSlackIntegration = integrations?.find((integration) => integration.id === slackIntegrationId)

    return (
        <div className="deprecated-space-y-3">
            <h3 className="mb-0">Destination</h3>
            <LemonField.Pure label="Destination type">
                <LemonSelect
                    value={selectedDestinationKey}
                    onChange={(destinationKey) =>
                        setSelectedDestinationKey(destinationKey as BillingAlertDestinationKey)
                    }
                    options={BILLING_ALERT_DESTINATION_SELECT_OPTIONS}
                />
            </LemonField.Pure>

            {selectedDestinationKey === 'slack' ? (
                integrationsLoading ? (
                    <Spinner />
                ) : !slackIntegrations.length ? (
                    <SlackNotConfiguredBanner />
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <IntegrationChoice
                            integration="slack"
                            value={slackIntegrationId ?? undefined}
                            onChange={(integrationId) => setSlackIntegrationId(integrationId)}
                        />
                        {selectedSlackIntegration ? (
                            <SlackChannelPicker
                                integration={selectedSlackIntegration as IntegrationType}
                                value={slackChannel ?? undefined}
                                onChange={setSlackChannel}
                            />
                        ) : null}
                    </div>
                )
            ) : (
                <LemonField.Pure label={destinationWebhookLabel(selectedDestinationKey)}>
                    <LemonInput
                        value={webhookUrl}
                        onChange={setWebhookUrl}
                        placeholder="https://..."
                        data-attr="billing-alert-webhook-url"
                    />
                </LemonField.Pure>
            )}
        </div>
    )
}

export function BillingAlertDestinationPanel(): JSX.Element | null {
    const { destinationAlertId, selectedDestinationKey, destinationSaving, canCreateDestination } =
        useValues(billingAlertsLogic)
    const { setDestinationAlertId, createDestination } = useActions(billingAlertsLogic)

    if (!destinationAlertId) {
        return null
    }

    return (
        <LemonModal
            isOpen
            onClose={() => setDestinationAlertId(null)}
            title="Add destination"
            width={600}
            data-attr="billing-alert-destination"
        >
            <div className="deprecated-space-y-4">
                <BillingAlertDestinationFields />
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        onClick={createDestination}
                        loading={destinationSaving}
                        disabledReason={
                            !canCreateDestination ? destinationDisabledReason(selectedDestinationKey) : undefined
                        }
                        data-attr="create-billing-alert-destination"
                    >
                        Add {destinationLabel(selectedDestinationKey)} destination
                    </LemonButton>
                </div>
            </div>
        </LemonModal>
    )
}

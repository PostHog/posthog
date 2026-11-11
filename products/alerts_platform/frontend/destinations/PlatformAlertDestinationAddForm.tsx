import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'

import {
    ALERT_PAGERDUTY_REGION_OPTIONS,
    ALERT_PAGERDUTY_SEVERITY_OPTIONS,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'

import { DESTINATION_TYPE_OPTIONS } from './platformAlertDestinationFormat'
import { platformAlertDestinationsLogic } from './platformAlertDestinationsLogic'

export function PlatformAlertDestinationAddForm(): JSX.Element {
    const {
        destinationForm,
        destinationFormErrors,
        slackIntegration,
        slackIntegrations,
        integrationsLoading,
        isDestinationFormSubmitting,
    } = useValues(platformAlertDestinationsLogic)
    const { setDestinationFormValue, submitDestinationForm, cancelAddingDestination } =
        useActions(platformAlertDestinationsLogic)

    // Plain fields rather than a kea-forms <Form>, because this sits inside the alert's own form.
    return (
        <div
            className="space-y-2 border rounded p-2"
            // Enter in the URL or key adds the destination. Without this it would submit or advance the alert's own
            // form, which drops what was typed here. The Slack picker keeps Enter for choosing a channel.
            onKeyDown={(event) => {
                if (
                    event.key === 'Enter' &&
                    destinationForm.type !== 'slack' &&
                    event.target instanceof HTMLInputElement
                ) {
                    event.preventDefault()
                    event.stopPropagation()
                    submitDestinationForm()
                }
            }}
        >
            <LemonField.Pure label="Type">
                <LemonSelect
                    value={destinationForm.type}
                    onChange={(type) => setDestinationFormValue('type', type)}
                    options={DESTINATION_TYPE_OPTIONS}
                    size="small"
                    data-attr="platform-alert-destination-type"
                />
            </LemonField.Pure>
            {destinationForm.type === 'slack' ? (
                integrationsLoading ? (
                    <Spinner />
                ) : slackIntegration ? (
                    <>
                        {slackIntegrations && slackIntegrations.length > 1 ? (
                            <LemonField.Pure label="Workspace">
                                <LemonSelect
                                    size="small"
                                    value={slackIntegration.id}
                                    options={slackIntegrations.map((integration) => ({
                                        value: integration.id,
                                        label: integration.display_name,
                                    }))}
                                    onChange={(workspaceId) => {
                                        setDestinationFormValue('slackWorkspaceId', workspaceId)
                                        // A channel ID belongs to one workspace.
                                        setDestinationFormValue('slackChannel', null)
                                    }}
                                    data-attr="platform-alert-destination-slack-workspace"
                                />
                            </LemonField.Pure>
                        ) : null}
                        <LemonField.Pure label="Channel" error={destinationFormErrors.slackChannel}>
                            <SlackChannelPicker
                                integration={slackIntegration}
                                value={destinationForm.slackChannel ?? undefined}
                                onChange={(channel) => setDestinationFormValue('slackChannel', channel)}
                            />
                        </LemonField.Pure>
                    </>
                ) : (
                    <SlackNotConfiguredBanner />
                )
            ) : destinationForm.type === 'pagerduty' ? (
                <>
                    <LemonField.Pure
                        label="Integration key"
                        error={destinationFormErrors.pagerDutyRoutingKey}
                        help='In PagerDuty, add an "Events API v2" integration to the service to page and paste its key. An incident opens when the alert fires and resolves when it stops.'
                    >
                        {/* Autocapture records copied text, which the password type does not stop. */}
                        <LemonInput
                            type="password"
                            autoComplete="off"
                            className="ph-no-capture"
                            size="small"
                            value={destinationForm.pagerDutyRoutingKey}
                            onChange={(key) => setDestinationFormValue('pagerDutyRoutingKey', key)}
                            placeholder="32-character Events API v2 integration key"
                            data-attr="platform-alert-destination-pagerduty-key"
                        />
                    </LemonField.Pure>
                    <div className="flex flex-wrap gap-2">
                        <LemonField.Pure label="Severity">
                            <LemonSelect
                                size="small"
                                value={destinationForm.pagerDutySeverity}
                                onChange={(severity) => setDestinationFormValue('pagerDutySeverity', severity)}
                                options={ALERT_PAGERDUTY_SEVERITY_OPTIONS}
                                data-attr="platform-alert-destination-pagerduty-severity"
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Service region">
                            <LemonSelect
                                size="small"
                                value={destinationForm.pagerDutyRegion}
                                onChange={(region) => setDestinationFormValue('pagerDutyRegion', region)}
                                options={ALERT_PAGERDUTY_REGION_OPTIONS}
                                data-attr="platform-alert-destination-pagerduty-region"
                            />
                        </LemonField.Pure>
                    </div>
                </>
            ) : (
                <LemonField.Pure label="URL" error={destinationFormErrors.webhookUrl}>
                    <LemonInput
                        // The URL's path carries the provider's secret, so typed text is not captured.
                        className="ph-no-capture"
                        size="small"
                        value={destinationForm.webhookUrl}
                        onChange={(url) => setDestinationFormValue('webhookUrl', url)}
                        placeholder="https://example.com/webhook"
                        data-attr="platform-alert-destination-webhook-url"
                    />
                </LemonField.Pure>
            )}
            <div className="flex justify-end gap-2">
                <LemonButton type="secondary" size="small" onClick={cancelAddingDestination}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={submitDestinationForm}
                    loading={isDestinationFormSubmitting}
                    data-attr="platform-alert-destination-save"
                >
                    Add
                </LemonButton>
            </div>
        </div>
    )
}

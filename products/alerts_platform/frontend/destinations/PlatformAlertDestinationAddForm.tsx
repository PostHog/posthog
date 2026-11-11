import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'

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
            // Enter in the URL adds the destination. Without this it would submit or advance the alert's own
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

import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { RECEIVER_TYPE_OPTIONS, keepsStoredUrl } from './platformAlertRoutingFormat'
import { platformAlertRoutingLogic } from './platformAlertRoutingLogic'

export function PlatformAlertReceiverModal(): JSX.Element {
    const {
        receiverModalOpen,
        editingReceiver,
        receiverForm,
        isReceiverFormSubmitting,
        slackIntegration,
        slackIntegrations,
        integrationsLoading,
    } = useValues(platformAlertRoutingLogic)
    const { closeReceiverModal, submitReceiverForm, setReceiverFormValue } = useActions(platformAlertRoutingLogic)
    const keepsUrl = keepsStoredUrl(receiverForm, editingReceiver)

    return (
        <LemonModal
            isOpen={receiverModalOpen}
            onClose={closeReceiverModal}
            title={editingReceiver ? 'Edit receiver' : 'New receiver'}
            description="A receiver is a destination that routes send matching alerts to."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeReceiverModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitReceiverForm}
                        loading={isReceiverFormSubmitting}
                        data-attr="platform-alert-receiver-save"
                    >
                        {editingReceiver ? 'Save' : 'Add receiver'}
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={platformAlertRoutingLogic}
                formKey="receiverForm"
                enableFormOnSubmit
                className="flex flex-col gap-4"
            >
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="Infra on-call" data-attr="platform-alert-receiver-name" />
                </LemonField>
                <LemonField name="type" label="Type">
                    <LemonSelect options={RECEIVER_TYPE_OPTIONS} fullWidth data-attr="platform-alert-receiver-type" />
                </LemonField>
                {receiverForm.type === 'slack' ? (
                    integrationsLoading ? (
                        <Spinner />
                    ) : slackIntegration ? (
                        <>
                            {slackIntegrations && slackIntegrations.length > 1 ? (
                                <LemonField name="slackWorkspaceId" label="Workspace">
                                    {({ onChange }) => (
                                        <LemonSelect
                                            fullWidth
                                            value={slackIntegration.id}
                                            options={slackIntegrations.map((integration) => ({
                                                value: integration.id,
                                                label: integration.display_name,
                                            }))}
                                            onChange={(workspaceId) => {
                                                onChange(workspaceId)
                                                // A channel ID belongs to one workspace.
                                                setReceiverFormValue('slackChannel', null)
                                            }}
                                            data-attr="platform-alert-receiver-slack-workspace"
                                        />
                                    )}
                                </LemonField>
                            ) : null}
                            <LemonField name="slackChannel" label="Channel">
                                {({ value, onChange }) => (
                                    <SlackChannelPicker
                                        integration={slackIntegration}
                                        value={value ?? undefined}
                                        onChange={onChange}
                                    />
                                )}
                            </LemonField>
                        </>
                    ) : (
                        <SlackNotConfiguredBanner />
                    )
                ) : (
                    <LemonField
                        name="webhookUrl"
                        label="Webhook URL"
                        help={keepsUrl ? 'Leave blank to keep the current URL.' : undefined}
                    >
                        <LemonInput
                            // The URL's path carries the provider's secret, so copied text is not captured.
                            className="ph-no-capture"
                            placeholder={keepsUrl ? editingReceiver?.webhook_url : 'https://example.com/webhook'}
                            data-attr="platform-alert-receiver-webhook-url"
                        />
                    </LemonField>
                )}
            </Form>
        </LemonModal>
    )
}

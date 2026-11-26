import { useActions, useValues } from 'kea'

import { LemonSelect, Spinner } from '@posthog/lemon-ui'

import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { platformAlertRoutingLogic } from './platformAlertRoutingLogic'

export function SlackReceiverFields(): JSX.Element {
    const { slackIntegration, slackIntegrations, integrationsLoading } = useValues(platformAlertRoutingLogic)
    const { setReceiverFormValue } = useActions(platformAlertRoutingLogic)

    return integrationsLoading ? (
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
                    <SlackChannelPicker integration={slackIntegration} value={value ?? undefined} onChange={onChange} />
                )}
            </LemonField>
        </>
    ) : (
        <SlackNotConfiguredBanner />
    )
}

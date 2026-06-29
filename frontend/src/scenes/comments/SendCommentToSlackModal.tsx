import { useActions, useValues } from 'kea'

import { LemonButton, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'

import { sendCommentToSlackLogic } from './sendCommentToSlackLogic'

export function SendCommentToSlackModal(): JSX.Element {
    const { isOpen, integrationId, channel, channelId, isSubmitting } = useValues(sendCommentToSlackLogic)
    const { closeModal, setIntegrationId, setChannel, submit } = useActions(sendCommentToSlackLogic)
    const { slackIntegrations } = useValues(integrationsLogic)

    const selectedIntegration = slackIntegrations?.find((integration) => integration.id === integrationId)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            title="Send discussion to Slack"
            description="Post this discussion thread to a Slack channel. Replies sync both ways."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submit}
                        loading={isSubmitting}
                        disabledReason={
                            !integrationId ? 'Select a workspace' : !channelId ? 'Select a channel' : undefined
                        }
                    >
                        Send to Slack
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                {!slackIntegrations?.length ? (
                    <SlackNotConfiguredBanner />
                ) : (
                    <>
                        <div className="flex flex-col gap-1">
                            <LemonLabel>Slack workspace</LemonLabel>
                            <IntegrationChoice
                                integration="slack"
                                value={integrationId ?? undefined}
                                onChange={(nextValue) => {
                                    setIntegrationId(nextValue ?? null)
                                }}
                            />
                        </div>
                        {selectedIntegration ? (
                            <div className="flex flex-col gap-1">
                                <LemonLabel>Channel</LemonLabel>
                                <SlackChannelPicker
                                    value={channel ?? undefined}
                                    onChange={(nextValue) => setChannel(nextValue ?? null)}
                                    integration={selectedIntegration}
                                />
                            </div>
                        ) : null}
                    </>
                )}
            </div>
        </LemonModal>
    )
}

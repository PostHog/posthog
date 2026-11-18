import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { sendCommentToSlackLogic } from './sendCommentToSlackLogic'
import { SlackDestinationPicker } from './SlackDestinationPicker'

export function SendCommentToSlackModal(): JSX.Element {
    const { isOpen, integrationId, channel, channelId, isSubmitting } = useValues(sendCommentToSlackLogic)
    const { closeModal, setIntegrationId, setChannel, submit } = useActions(sendCommentToSlackLogic)

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
                            !integrationId
                                ? 'Select a Slack workspace'
                                : !channelId
                                  ? 'Select a Slack channel'
                                  : undefined
                        }
                    >
                        Send to Slack
                    </LemonButton>
                </>
            }
        >
            <SlackDestinationPicker
                integrationId={integrationId}
                channel={channel}
                onIntegrationChange={setIntegrationId}
                onChannelChange={setChannel}
            />
        </LemonModal>
    )
}

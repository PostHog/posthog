import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconRecord } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { FeedbackRecordingAttachment } from 'lib/components/Support/FeedbackRecordingAttachment'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { MessageInput } from '../Chat/MessageInput'
import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

export function NewTicket(): JSX.Element {
    const { messageSending, feedbackRecordingResult, prefillMessage } = useValues(sidepanelTicketsLogic)
    const { sendMessage, setView, startFeedbackRecording } = useActions(sidepanelTicketsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <LemonButton
                    icon={<IconArrowLeft />}
                    size="small"
                    onClick={() => setView('list')}
                    data-attr="sidebar-go-back-to-tickets"
                />
                <span className="font-semibold">New ticket</span>
            </div>

            <p className="text-sm text-muted-alt m-0">
                Describe what you need help with and our team will get back to you.
            </p>

            {featureFlags[FEATURE_FLAGS.FEEDBACK_AUDIO_RECORDING] && (
                <Tooltip title="Start a screen recording to walk us through your issue">
                    <LemonButton
                        type="secondary"
                        center
                        fullWidth
                        onClick={startFeedbackRecording}
                        icon={<IconRecord color="red" />}
                    >
                        {feedbackRecordingResult ? 'Re-record' : 'Show us your issue'}
                    </LemonButton>
                </Tooltip>
            )}

            <MessageInput
                onSendMessage={(content, _richContent, _isPrivate, onSuccess) => sendMessage(content, onSuccess)}
                messageSending={messageSending}
                placeholder="What can we help you with?"
                buttonText="Submit ticket"
                minRows={4}
                initialContent={prefillMessage}
                belowEditor={feedbackRecordingResult ? <FeedbackRecordingAttachment /> : undefined}
            />
        </div>
    )
}
